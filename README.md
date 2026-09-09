# Grocery Tracker

Turns grocery receipts already sitting in paperless-ngx into itemized,
queryable insights — monthly category spend, per-item price history, and
cross-store price comparison.

It piggybacks entirely on your existing paperless-ngx pipeline:

```
receipt photo -> paperless-ngx consume folder -> OCR'd by paperless-ngx/paperless-gpt
             -> tagged with your configured trigger tag(s) (via a paperless-ngx
                workflow, or tags an existing paperless-gpt classification step
                already applies)
             -> grocery-tracker polls for documents having ALL of those tags,
                reads the OCR'd `content` field, and asks GPT-4o to turn it
                into structured JSON
             -> saved to its own Postgres DB
             -> tag flips to "receipt-processed" (or "receipt-error")
             -> dashboard at :8030 reads the DB
```

No images are re-sent to the LLM — it reuses the OCR text paperless-ngx
already extracted, so this only costs a small text completion per receipt.

**Item name normalization.** Receipts word the same product differently
("Yellow Onions", "Onions 3lb Bag", "Red Onion"). Before saving, each raw
item name is checked against your existing canonical item list and either
matched to one (e.g. all three above -> "Onion") or added as a new
canonical item if it's genuinely new — using a cheap `gpt-4o-mini` call by
default (`NORMALIZATION_LLM_MODEL` env var to change it). The raw wording
is still kept per line item (so the dashboard's receipt tape shows what
the receipt actually said), while price history, store comparison, and
search all operate on the canonical name, so variants merge automatically.
You can inspect/edit the mapping directly via the `canonical_items` table
if the LLM ever merges or splits something you'd rather it hadn't.

## 1. Folder for receipts

Create a dedicated subfolder so receipts don't mix with your other documents:

```bash
mkdir -p /mnt/truenas/paperless/consume/receipts
```

## 2. Tag receipts for grocery-tracker to pick up

grocery-tracker polls paperless-ngx for documents that have **all** of the
tags listed in `RECEIPT_TRIGGER_TAGS` (comma-separated):

```
RECEIPT_TRIGGER_TAGS=Receipt,Grocery
```

This assumes an existing paperless-gpt (or other) workflow already tags
documents `Receipt` and classifies them into `Grocery` / `Restaurant` /
etc. grocery-tracker only picks up documents that have *both* tags, and
leaves those tags alone (it adds `receipt-processed`/`receipt-error` on top
rather than removing anything).

## 3. Deploy as its own stack

grocery-tracker is a standalone stack (`docker-compose.yml`) — it doesn't
need to live in the same compose file as paperless-ngx. It talks to
paperless-ngx purely over its HTTP API (same as a browser would), so the
two stacks don't even need to share a docker network.

**Via Portainer (git-based stack, auto-deploy on push):**

1. **Stacks → Add stack → Repository**
2. Repository URL: your private GitHub repo for this project
   (`https://github.com/<you>/grocery-tracker`), branch `main`
3. Compose path: `docker-compose.yml`
4. Environment variables: paste in the values from `.env.example`
   (`GROCERY_DB_PASSWORD`, `PAPERLESS_BASE_URL`, `PAPERLESS_PUBLIC_URL`,
   `PAPERLESS_API_TOKEN`, `OPENAI_API_KEY`, etc.) — entered here, not
   committed to the repo
5. **GitOps updates**: enable, with either:
   - **Polling** (e.g. every 5 min) — Portainer checks the repo and
     redeploys on new commits, no webhook needed, or
   - **Webhook** — copy the webhook URL Portainer gives you into the
     GitHub repo's **Settings → Webhooks**, so a push redeploys immediately

From then on, `git push` to `main` auto-deploys.

**Via plain `docker compose` instead:**

```bash
cp .env.example .env   # fill in real values
docker compose up -d --build
```

## 4. Use it

- Drop a receipt photo/scan into `/mnt/truenas/paperless/consume/receipts/`
- Wait for paperless-ngx to consume + OCR it, and for it to end up with all
  of your `RECEIPT_TRIGGER_TAGS` tags (usually within seconds)
- grocery-tracker polls every 60s by default (`POLL_INTERVAL_SECONDS`) — check
  its logs with `docker compose logs -f grocery-tracker`
- Once tagged `receipt-processed`, open the dashboard at
  `http://<your-host>:8030`

If a receipt fails to parse (e.g. OCR text was empty or the LLM response
was malformed), it's tagged `receipt-error` (in addition to its existing
tags) instead of looping forever — check `docker compose logs grocery-tracker`
for the reason, and look at `processing_errors` in the `grocery` database for
the full history.

## Running the tests

```bash
cd app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

This runs the unit test suite (`app/tests/`) — `extractor.py` and
`normalizer.py` with the OpenAI calls mocked via `responses`, so it's fast,
free, and doesn't need a real `OPENAI_API_KEY`.

There's a second suite, `app/tests/eval/`, that calls the real OpenAI API to
check the normalization prompt still makes the judgement calls it's supposed
to (e.g. "Green Onion" stays separate from "Onion", "BEER CRV" doesn't get
categorized as "Beer"). It's excluded by default and skips itself if there's
no real API key configured. Run it explicitly after changing either
`SYSTEM_PROMPT` in `extractor.py`/`normalizer.py`:

```bash
OPENAI_API_KEY=sk-... pytest -m eval
```

It costs real API calls and is non-deterministic, so it's not meant to run
on every commit — only when you've touched a prompt.

## Known limitations / good next steps

- **Normalization isn't perfect.** The LLM decides merges based on judgement
  (e.g. keeping "Green Onion" separate from "Onion"), and it only sees your
  *existing* canonical list at normalization time, not the full purchase
  history - if you spot a bad merge or split, fix it directly in the
  `canonical_items` / `line_items.canonical_item_id` columns in Postgres.
- **No manual correction UI yet.** If GPT-4o misreads a price or quantity,
  the only fix right now is editing the row directly in Postgres. A review
  screen (like paperless-gpt's own manual-matching UI) would be a natural
  next addition if this happens often.
- **No retry-with-backoff on errors** — a receipt that fails is tagged
  `receipt-error` and left alone; you'd remove that tag manually in
  paperless-ngx to retry after investigating.
- **Categories are whatever GPT-4o picks** from a fixed list in
  `extractor.py` — edit `VALID_CATEGORIES` there if you want different
  buckets.
