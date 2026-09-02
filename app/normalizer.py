import os
import json
import logging
import requests

log = logging.getLogger("grocery-tracker.normalizer")

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
# Normalization is a simpler task than receipt parsing, so this defaults to a
# cheaper model - override if you'd rather use the same model as extraction.
NORMALIZATION_LLM_MODEL = os.environ.get("NORMALIZATION_LLM_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You normalize grocery item names so the same product is tracked
consistently over time and across stores, even when receipts word it differently.

You will be given:
1. A list of canonical item names already in use (may be empty on first run).
2. A list of new raw item names just extracted from a receipt.

For each new raw name, decide:
- If it refers to the same core product as an existing canonical name - ignoring minor
  variety, size, or brand descriptors (e.g. "Yellow Onions", "Onions 3lb Bag", and "Red
  Onion" all -> "Onion") - reuse that EXACT existing canonical name, character for character.
- Otherwise, propose a new canonical name: singular, title case, no brand names, no
  package sizes/weights (e.g. "Tomato" not "Roma Tomatoes 2lb", "Milk" not "Organic Whole
  Milk Gallon" unless the type meaningfully changes how you'd shop for it, e.g. keep "Whole
  Milk" separate from "Almond Milk" - they are not substitutes).

Only merge items a shopper would treat as literally the same grocery item for price
comparison. Keep genuinely different foods separate even if related (e.g. "Sweet Potato" is
not "Potato"; "Green Onion" (scallion) is not "Onion"; "Almond Milk" is not "Milk").

Be especially careful with color/ripeness descriptors: usually cosmetic (merge them), but
sometimes they mark a different product bought and used differently - keep those separate.
For example "Banana Green" (raw/unripe banana, sold and cooked as a vegetable) is NOT the
same product as "Banana"/"Banana Regular" (ripe banana eaten as fruit), even though both are
literally bananas - a shopper comparing prices would not treat them as substitutes.

Never merge based on superficial name/spelling similarity alone - check the actual product
category matches. For example "Britannia Bourbon" (a chocolate cream biscuit, a snack) is NOT
"Brioche" (a bread) just because the words sound alike.

A raw name for a deposit/redemption fee or a bag charge (e.g. "BEER CRV", "CA REDEMP VA",
"PAPER Bag") is never the same item as the product it's printed next to or named after - "BEER
CRV" is a bottle deposit, not "Beer", even though the word appears in it. Give these their own
canonical name (e.g. "CRV Deposit", "Bag Fee") separate from any real product.

Never propose a generic placeholder canonical name such as "Unknown", "Other",
"Miscellaneous", or "Item" - even for an unfamiliar product, a store SKU/code, or a
non-grocery purchase (clothing, household goods, medicine, a bottle deposit fee), invent a
specific canonical name from the raw text itself. Two unrelated products must never end up
sharing the same canonical name just because you couldn't identify either of them.

Respond with ONLY valid JSON mapping each raw name to its canonical name, no markdown
fences, no commentary:
{"raw name 1": "Canonical Name", "raw name 2": "Canonical Name"}
"""


def normalize_items(raw_names: list, known_canonical_names: list) -> dict:
    """Returns {raw_name: canonical_name} for every raw_name given.
    Falls back to raw_name unchanged (title-cased) for any name the LLM
    fails to map, so a normalization hiccup never blocks saving a receipt."""
    if not raw_names:
        return {}

    user_content = json.dumps({
        "existing_canonical_names": known_canonical_names,
        "new_raw_names": raw_names,
    })

    fallback = {name: name.strip().title() for name in raw_names}

    try:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": NORMALIZATION_LLM_MODEL,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        if not resp.ok:
            log.error(
                "Normalization call failed (%s), falling back to raw names title-cased: %s",
                resp.status_code, resp.text,
            )
            return fallback
        raw = resp.json()["choices"][0]["message"]["content"]
        mapping = json.loads(raw)
    except Exception as e:
        log.error("Normalization call failed, falling back to raw names title-cased: %s", e)
        return fallback

    # Make sure every requested raw name has a mapping, even if the LLM
    # skipped one or hallucinated extra keys.
    result = {}
    for name in raw_names:
        result[name] = mapping.get(name) or fallback[name]
    return result
