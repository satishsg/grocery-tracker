import os
import json
import logging
import requests

log = logging.getLogger("grocery-tracker.extractor")

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("EXTRACTION_LLM_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

VALID_CATEGORIES = [
    "produce", "dairy", "meat", "seafood", "bakery", "frozen",
    "pantry", "beverages", "snacks", "household", "personal_care", "fee", "other",
]

SYSTEM_PROMPT = f"""You extract structured data from grocery/store receipt text that has
already been OCR'd. The text may contain a pipe-delimited item table, tax codes (N/S) at
the end of lines, and separate "Regular Price" / "You Saved" lines that apply to the item
listed immediately above them - fold any such discount info into that item's final paid
price rather than creating separate line items for them.

Respond with ONLY valid JSON (no markdown fences, no commentary) matching exactly this shape:

{{
  "store": "string - the store name",
  "date": "YYYY-MM-DD",
  "total": number or null,
  "items": [
    {{
      "name": "string - clean product name, without package-size text or SKU codes",
      "category": "one of: {', '.join(VALID_CATEGORIES)}",
      "quantity": number,
      "unit": "one of: lb, oz, kg, g, each, gal, l, ml, dozen",
      "unit_price": number,
      "total_price": number - the actual amount paid for this line, after any discount
    }}
  ]
}}

Rules:
- Use category "fee" for a mandatory container/bottle deposit (e.g. "CRV", "CA REDEMP") or a
  carry/paper bag charge - these are not grocery products and should never share a category
  with whatever product they're printed next to on the receipt.
- If a line shows "qty @ price" (e.g. "2.70 @ 0.99"), quantity is the first number and
  unit_price is the second; assume unit "lb" if no unit is given and the quantity looks
  like a weight (has a decimal), otherwise use "each" with quantity as the item count.
- Ignore tax code letters (N, S, etc.) at the end of lines - they are not part of the price.
- Skip subtotal, tax, and total summary lines - don't include them as items.
- If the date includes a time, drop the time and keep only YYYY-MM-DD.
- If you cannot confidently determine a field, make your best reasonable estimate rather
  than omitting it, except you may set "total" to null if truly not present.
"""


def extract_receipt(content_text: str) -> dict:
    """Calls the LLM with the OCR'd receipt content and returns parsed structured data.
    Raises ValueError if the response isn't valid JSON matching the expected shape."""
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content_text},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\nRaw response: {raw[:500]}")

    if "store" not in data or "date" not in data or "items" not in data:
        raise ValueError(f"LLM response missing required fields: {raw[:500]}")

    if not data["items"]:
        raise ValueError("LLM extracted zero line items - refusing to save an empty receipt")

    return data
