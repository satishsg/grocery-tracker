import os
import logging
import requests

log = logging.getLogger("grocery-tracker.paperless")

BASE_URL = os.environ["PAPERLESS_BASE_URL"].rstrip("/")
API_TOKEN = os.environ["PAPERLESS_API_TOKEN"]

# The URL a browser can reach to open a document in the paperless-ngx UI - may
# differ from BASE_URL, which is often an internal docker-network hostname
# (e.g. http://paperless-webserver:8000) that isn't reachable from outside.
PUBLIC_URL = os.environ.get("PAPERLESS_PUBLIC_URL", BASE_URL).rstrip("/")

# A document must have ALL of these tags to be picked up. Point this at tags
# an existing paperless-gpt workflow already applies (e.g. "receipts,Grocery")
# instead of standing up a separate receipt-inbox workflow.
TRIGGER_TAGS = [t.strip() for t in os.environ.get("RECEIPT_TRIGGER_TAGS", "receipt-inbox").split(",") if t.strip()]
PROCESSED_TAG = os.environ.get("RECEIPT_PROCESSED_TAG", "receipt-processed")
ERROR_TAG = os.environ.get("RECEIPT_ERROR_TAG", "receipt-error")

HEADERS = {"Authorization": f"Token {API_TOKEN}"}


def _get(path, **kwargs):
    resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def _patch(path, json_body):
    resp = requests.patch(f"{BASE_URL}{path}", headers=HEADERS, json=json_body, timeout=30)
    resp.raise_for_status()
    return resp


def get_tag_id(tag_name: str, create_if_missing=True):
    resp = _get("/api/tags/", params={"name__iexact": tag_name})
    results = resp.json().get("results", [])
    if results:
        return results[0]["id"]
    if not create_if_missing:
        return None
    resp = requests.post(
        f"{BASE_URL}/api/tags/", headers=HEADERS, json={"name": tag_name}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["id"]


def get_documents_needing_processing():
    """Documents having ALL of TRIGGER_TAGS, and none of PROCESSED_TAG/ERROR_TAG yet."""
    trigger_ids = [get_tag_id(name, create_if_missing=False) for name in TRIGGER_TAGS]
    if any(tid is None for tid in trigger_ids):
        return []

    params = {"tags__id__all": ",".join(str(i) for i in trigger_ids), "page_size": 100}
    exclude_ids = [
        tid for tid in (
            get_tag_id(PROCESSED_TAG, create_if_missing=False),
            get_tag_id(ERROR_TAG, create_if_missing=False),
        )
        if tid is not None
    ]
    if exclude_ids:
        params["tags__id__none"] = ",".join(str(i) for i in exclude_ids)

    resp = _get("/api/documents/", params=params)
    return resp.json().get("results", [])


def get_document(document_id: int):
    """Returns the full document metadata, including the OCR'd `content` field
    that paperless-ngx (and paperless-gpt, if LLM OCR is enabled) already produced."""
    return _get(f"/api/documents/{document_id}/").json()


def get_document_content(document_id: int) -> str:
    doc = get_document(document_id)
    return doc.get("content", "") or ""


def set_tags(document_id: int, tag_ids):
    _patch(f"/api/documents/{document_id}/", {"tags": tag_ids})


def add_tag(document_id: int, current_tag_ids, tag_name: str):
    """Adds tag_name to the document without disturbing its other tags
    (trigger tags like 'receipts'/'Grocery' belong to other workflows, not us)."""
    tag_id = get_tag_id(tag_name, create_if_missing=True)
    if tag_id in current_tag_ids:
        return
    set_tags(document_id, list(current_tag_ids) + [tag_id])
