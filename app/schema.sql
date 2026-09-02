-- Grocery tracker schema

CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id SERIAL PRIMARY KEY,
    paperless_document_id INTEGER UNIQUE NOT NULL,
    store_id INTEGER REFERENCES stores(id),
    purchase_date DATE NOT NULL,
    total_amount NUMERIC(10, 2),
    raw_extraction JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical_items (
    id SERIAL PRIMARY KEY,
    canonical_name TEXT UNIQUE NOT NULL,
    category TEXT
);

CREATE TABLE IF NOT EXISTS line_items (
    id SERIAL PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    item_name TEXT NOT NULL,             -- raw name as extracted from this receipt
    canonical_item_id INTEGER REFERENCES canonical_items(id),
    category TEXT,
    quantity NUMERIC(10, 3),
    unit TEXT,
    unit_price NUMERIC(10, 4),
    total_price NUMERIC(10, 2)
);

-- Safe to re-run: adds the column if this schema is being applied to a
-- database that was created before canonical_items existed.
ALTER TABLE line_items ADD COLUMN IF NOT EXISTS canonical_item_id INTEGER REFERENCES canonical_items(id);

CREATE TABLE IF NOT EXISTS processing_errors (
    id SERIAL PRIMARY KEY,
    paperless_document_id INTEGER NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_line_items_item_name ON line_items (lower(item_name));
CREATE INDEX IF NOT EXISTS idx_line_items_canonical_item_id ON line_items (canonical_item_id);
CREATE INDEX IF NOT EXISTS idx_receipts_purchase_date ON receipts (purchase_date);
CREATE INDEX IF NOT EXISTS idx_line_items_category ON line_items (category);
