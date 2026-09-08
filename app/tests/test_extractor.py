import json

import pytest
import responses
import requests

import extractor

CHAT_URL = f"{extractor.OPENAI_BASE_URL}/chat/completions"

VALID_RESPONSE = {
    "store": "Test Mart",
    "date": "2026-01-01",
    "total": 1.99,
    "items": [
        {
            "name": "Onion",
            "category": "produce",
            "quantity": 1,
            "unit": "each",
            "unit_price": 1.99,
            "total_price": 1.99,
        }
    ],
}


def _llm_response(content) -> dict:
    body = content if isinstance(content, str) else json.dumps(content)
    return {"choices": [{"message": {"content": body}}]}


@responses.activate
def test_returns_parsed_data_on_valid_response():
    responses.add(responses.POST, CHAT_URL, json=_llm_response(VALID_RESPONSE), status=200)

    result = extractor.extract_receipt("some ocr text")

    assert result == VALID_RESPONSE


@responses.activate
def test_raises_on_malformed_json():
    responses.add(responses.POST, CHAT_URL, json=_llm_response("not json"), status=200)

    with pytest.raises(ValueError, match="did not return valid JSON"):
        extractor.extract_receipt("some ocr text")


@responses.activate
def test_raises_on_missing_required_fields():
    incomplete = {"store": "Test Mart", "items": []}
    responses.add(responses.POST, CHAT_URL, json=_llm_response(incomplete), status=200)

    with pytest.raises(ValueError, match="missing required fields"):
        extractor.extract_receipt("some ocr text")


@responses.activate
def test_raises_on_zero_line_items():
    no_items = {"store": "Test Mart", "date": "2026-01-01", "total": 0, "items": []}
    responses.add(responses.POST, CHAT_URL, json=_llm_response(no_items), status=200)

    with pytest.raises(ValueError, match="zero line items"):
        extractor.extract_receipt("some ocr text")


@responses.activate
def test_raises_on_http_error():
    responses.add(responses.POST, CHAT_URL, json={"error": "server error"}, status=500)

    with pytest.raises(requests.exceptions.HTTPError):
        extractor.extract_receipt("some ocr text")
