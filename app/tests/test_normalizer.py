import json

import requests
import responses

import normalizer

CHAT_URL = f"{normalizer.OPENAI_BASE_URL}/chat/completions"


def _llm_response(mapping: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(mapping)}}]}


def test_no_raw_names_makes_no_http_call():
    assert normalizer.normalize_items([], ["Onion"]) == {}


@responses.activate
def test_maps_raw_names_to_canonical_names():
    responses.add(
        responses.POST,
        CHAT_URL,
        json=_llm_response({"Yellow Onions": "Onion", "Onions 3lb Bag": "Onion"}),
        status=200,
    )

    result = normalizer.normalize_items(["Yellow Onions", "Onions 3lb Bag"], ["Onion"])

    assert result == {"Yellow Onions": "Onion", "Onions 3lb Bag": "Onion"}


@responses.activate
def test_falls_back_to_title_case_on_http_error():
    responses.add(responses.POST, CHAT_URL, json={"error": "bad request"}, status=400)

    result = normalizer.normalize_items(["weird item"], [])

    assert result == {"weird item": "Weird Item"}


@responses.activate
def test_falls_back_to_title_case_on_request_exception():
    responses.add(responses.POST, CHAT_URL, body=requests.exceptions.ConnectionError("boom"))

    result = normalizer.normalize_items(["weird item"], [])

    assert result == {"weird item": "Weird Item"}


@responses.activate
def test_falls_back_to_title_case_on_malformed_json_content():
    responses.add(
        responses.POST,
        CHAT_URL,
        json={"choices": [{"message": {"content": "not json"}}]},
        status=200,
    )

    result = normalizer.normalize_items(["weird item"], [])

    assert result == {"weird item": "Weird Item"}


@responses.activate
def test_falls_back_for_raw_names_missing_from_llm_mapping():
    responses.add(
        responses.POST,
        CHAT_URL,
        json=_llm_response({"some other name": "Something Else"}),
        status=200,
    )

    result = normalizer.normalize_items(["weird item"], [])

    assert result == {"weird item": "Weird Item"}


@responses.activate
def test_ignores_hallucinated_extra_keys_from_llm():
    responses.add(
        responses.POST,
        CHAT_URL,
        json=_llm_response({"Onion": "Onion", "made up item": "Made Up Item"}),
        status=200,
    )

    result = normalizer.normalize_items(["Onion"], ["Onion"])

    assert result == {"Onion": "Onion"}
