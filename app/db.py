import os
import json
import logging
from contextlib import contextmanager

import psycopg2
import psycopg2.extras

log = logging.getLogger("grocery-tracker.db")

DB_HOST = os.environ.get("GROCERY_DB_HOST", "grocery-db")
DB_PORT = os.environ.get("GROCERY_DB_PORT", "5432")
DB_NAME = os.environ.get("GROCERY_DB_NAME", "grocery")
DB_USER = os.environ.get("GROCERY_DB_USER", "grocery")
DB_PASSWORD = os.environ.get("GROCERY_DB_PASSWORD", "grocery")


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD
    )


@contextmanager
def cursor(commit=False):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(schema_sql)
        conn.commit()
        log.info("Schema initialized")
    finally:
        conn.close()


def get_or_create_store(name: str) -> int:
    name = name.strip()
    with cursor(commit=True) as cur:
        cur.execute("SELECT id FROM stores WHERE lower(name) = lower(%s)", (name,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute("INSERT INTO stores (name) VALUES (%s) RETURNING id", (name,))
        return cur.fetchone()["id"]


def get_all_canonical_names() -> list:
    with cursor() as cur:
        cur.execute("SELECT canonical_name FROM canonical_items ORDER BY canonical_name")
        return [r["canonical_name"] for r in cur.fetchall()]


def get_or_create_canonical_item(canonical_name: str, category: str = None) -> int:
    canonical_name = canonical_name.strip()
    with cursor(commit=True) as cur:
        cur.execute(
            "SELECT id FROM canonical_items WHERE lower(canonical_name) = lower(%s)",
            (canonical_name,),
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO canonical_items (canonical_name, category) VALUES (%s, %s) RETURNING id",
            (canonical_name, category),
        )
        return cur.fetchone()["id"]


def receipt_exists(paperless_document_id: int) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM receipts WHERE paperless_document_id = %s",
            (paperless_document_id,),
        )
        return cur.fetchone() is not None


def save_receipt(paperless_document_id: int, extraction: dict, canonical_map: dict = None):
    """Persist a parsed receipt (store, date, total, line items) to the DB.

    canonical_map: {raw_item_name: canonical_name}, as produced by normalizer.normalize_items().
    If omitted, each item's raw name is used as its own canonical name unchanged.
    """
    canonical_map = canonical_map or {}
    store_id = get_or_create_store(extraction["store"])
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO receipts (paperless_document_id, store_id, purchase_date, total_amount, raw_extraction)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (paperless_document_id) DO NOTHING
            RETURNING id
            """,
            (
                paperless_document_id,
                store_id,
                extraction["date"],
                extraction.get("total"),
                json.dumps(extraction),
            ),
        )
        row = cur.fetchone()
        if row is None:
            log.info("Receipt for document %s already exists, skipping", paperless_document_id)
            return
        receipt_id = row["id"]

        for item in extraction.get("items", []):
            canonical_name = canonical_map.get(item["name"], item["name"])
            canonical_item_id = get_or_create_canonical_item(canonical_name, item.get("category"))
            cur.execute(
                """
                INSERT INTO line_items
                    (receipt_id, item_name, canonical_item_id, category, quantity, unit, unit_price, total_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    receipt_id,
                    item["name"],
                    canonical_item_id,
                    item.get("category"),
                    item.get("quantity"),
                    item.get("unit"),
                    item.get("unit_price"),
                    item.get("total_price"),
                ),
            )
    log.info("Saved receipt %s (%s items)", receipt_id, len(extraction.get("items", [])))


def log_processing_error(paperless_document_id: int, message: str):
    with cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO processing_errors (paperless_document_id, error_message) VALUES (%s, %s)",
            (paperless_document_id, message),
        )


# ---- Dashboard queries ----

def monthly_summary(year: int, month: int):
    with cursor() as cur:
        cur.execute(
            """
            SELECT li.category,
                   SUM(li.total_price) AS total,
                   COUNT(*) AS item_count
            FROM line_items li
            JOIN receipts r ON r.id = li.receipt_id
            WHERE date_part('year', r.purchase_date) = %s
              AND date_part('month', r.purchase_date) = %s
            GROUP BY li.category
            ORDER BY total DESC
            """,
            (year, month),
        )
        by_category = cur.fetchall()

        cur.execute(
            """
            SELECT COALESCE(SUM(li.total_price), 0) AS grand_total,
                   COUNT(DISTINCT r.id) AS receipt_count
            FROM line_items li
            JOIN receipts r ON r.id = li.receipt_id
            WHERE date_part('year', r.purchase_date) = %s
              AND date_part('month', r.purchase_date) = %s
            """,
            (year, month),
        )
        totals = cur.fetchone()

        cur.execute(
            """
            SELECT li.item_name,
                   li.category,
                   s.name AS store,
                   li.quantity,
                   li.unit,
                   li.unit_price,
                   li.total_price,
                   r.purchase_date,
                   r.paperless_document_id
            FROM line_items li
            JOIN receipts r ON r.id = li.receipt_id
            JOIN stores s ON s.id = r.store_id
            WHERE date_part('year', r.purchase_date) = %s
              AND date_part('month', r.purchase_date) = %s
            ORDER BY r.purchase_date DESC, li.item_name
            """,
            (year, month),
        )
        items = cur.fetchall()

    return {"by_category": by_category, "totals": totals, "items": items}


def item_price_history(item_name: str):
    """item_name is matched against the canonical name (as returned by list_known_items),
    so this automatically covers every raw variant (e.g. 'yellow onions', 'onions') that
    was normalized into it."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.purchase_date, s.name AS store, li.quantity, li.unit,
                   li.unit_price, li.total_price, li.item_name AS raw_item_name,
                   r.paperless_document_id
            FROM line_items li
            JOIN receipts r ON r.id = li.receipt_id
            JOIN stores s ON s.id = r.store_id
            JOIN canonical_items ci ON ci.id = li.canonical_item_id
            WHERE lower(ci.canonical_name) = lower(%s)
              AND ci.category IS DISTINCT FROM 'fee'
            ORDER BY r.purchase_date ASC
            """,
            (item_name,),
        )
        return cur.fetchall()


# Wholesale/club stores sell in bulk pack sizes, so their "unit price" isn't
# comparable to a regular grocery store's - excluded from store_comparison.
WHOLESALE_STORES = ["costco"]


def store_comparison(item_name: str):
    """Every purchase of this item, grouped by store (most recent first within
    each store) - intentionally not collapsed to one row per store, so this
    always has the same number of rows as item_price_history's data points."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT s.name AS store, li.unit_price, li.unit, r.purchase_date,
                   r.paperless_document_id
            FROM line_items li
            JOIN receipts r ON r.id = li.receipt_id
            JOIN stores s ON s.id = r.store_id
            JOIN canonical_items ci ON ci.id = li.canonical_item_id
            WHERE lower(ci.canonical_name) = lower(%s)
              AND ci.category IS DISTINCT FROM 'fee'
              AND NOT (lower(s.name) LIKE ANY (%s))
            ORDER BY s.name, r.purchase_date DESC
            """,
            (item_name, [f"%{w}%" for w in WHOLESALE_STORES]),
        )
        return cur.fetchall()


def list_known_items(search: str = ""):
    """Returns canonical item names (not raw receipt wording) for search/autocomplete."""
    with cursor() as cur:
        if search:
            cur.execute(
                """
                SELECT canonical_name FROM canonical_items
                WHERE canonical_name ILIKE %s AND category IS DISTINCT FROM 'fee'
                ORDER BY canonical_name
                """,
                (f"%{search}%",),
            )
        else:
            cur.execute(
                "SELECT canonical_name FROM canonical_items WHERE category IS DISTINCT FROM 'fee' ORDER BY canonical_name"
            )
        return [r["canonical_name"] for r in cur.fetchall()]


def available_months():
    with cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT date_part('year', purchase_date)::int AS year,
                             date_part('month', purchase_date)::int AS month
            FROM receipts
            ORDER BY year DESC, month DESC
            """
        )
        return cur.fetchall()
