import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import db
import extractor
import normalizer
import paperless_client

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("grocery-tracker")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))


def process_document(doc: dict):
    document_id = doc["id"]

    if db.receipt_exists(document_id):
        log.info("Document %s already has a saved receipt, just fixing tags", document_id)
        paperless_client.add_tag(document_id, doc.get("tags", []), paperless_client.PROCESSED_TAG)
        return

    log.info("Processing document %s (%s)", document_id, doc.get("title"))
    try:
        content = paperless_client.get_document_content(document_id)
        if not content.strip():
            raise ValueError("Document has no OCR content yet - paperless may still be processing it")

        extraction = extractor.extract_receipt(content)

        raw_names = [item["name"] for item in extraction["items"]]
        known_canonical_names = db.get_all_canonical_names()
        canonical_map = normalizer.normalize_items(raw_names, known_canonical_names)
        log.info("Normalized names for document %s: %s", document_id, canonical_map)

        db.save_receipt(document_id, extraction, canonical_map)
        paperless_client.add_tag(document_id, doc.get("tags", []), paperless_client.PROCESSED_TAG)
        log.info("Document %s processed successfully", document_id)
    except Exception as e:
        log.error("Failed to process document %s: %s", document_id, e)
        db.log_processing_error(document_id, str(e))
        paperless_client.add_tag(document_id, doc.get("tags", []), paperless_client.ERROR_TAG)


async def poll_loop():
    while True:
        try:
            docs = await asyncio.to_thread(paperless_client.get_documents_needing_processing)
            if docs:
                log.info("Found %d document(s) tagged %s", len(docs), paperless_client.TRIGGER_TAGS)
            for doc in docs:
                await asyncio.to_thread(process_document, doc)
        except Exception as e:
            log.error("Poll loop error: %s", e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_schema()
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()


app = FastAPI(title="Grocery Tracker", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(os.path.dirname(__file__), "templates", "index.html")) as f:
        return f.read()


@app.get("/api/config")
def api_config():
    return {"paperless_public_url": paperless_client.PUBLIC_URL}


@app.get("/api/months")
def api_months():
    return db.available_months()


@app.get("/api/monthly")
def api_monthly(year: int = Query(...), month: int = Query(...)):
    return db.monthly_summary(year, month)


@app.get("/api/items")
def api_items(search: str = ""):
    return db.list_known_items(search)


@app.get("/api/item-history")
def api_item_history(name: str = Query(...)):
    return db.item_price_history(name)


@app.get("/api/store-comparison")
def api_store_comparison(name: str = Query(...)):
    return db.store_comparison(name)


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
