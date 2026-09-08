import os

import pytest

import normalizer

pytestmark = pytest.mark.eval

if os.environ.get("OPENAI_API_KEY") in (None, "test-key"):
    pytest.skip(
        "eval tests call the real OpenAI API; export a real OPENAI_API_KEY to run them",
        allow_module_level=True,
    )

PLACEHOLDER_NAMES = {"unknown", "other", "miscellaneous", "item", "n/a"}


def _merged(mapping, *raw_names):
    return len({mapping[name] for name in raw_names}) == 1


def test_cosmetic_variants_of_onion_merge():
    mapping = normalizer.normalize_items(["Yellow Onions", "Onions 3lb Bag", "Red Onion"], [])
    assert _merged(mapping, "Yellow Onions", "Onions 3lb Bag", "Red Onion")


def test_reuses_an_existing_canonical_name_exactly():
    mapping = normalizer.normalize_items(["Yellow Onions"], ["Onion"])
    assert mapping["Yellow Onions"] == "Onion"


def test_scallion_does_not_merge_with_onion():
    mapping = normalizer.normalize_items(["Onion", "Green Onion"], [])
    assert mapping["Onion"] != mapping["Green Onion"]


def test_sweet_potato_does_not_merge_with_potato():
    mapping = normalizer.normalize_items(["Potato", "Sweet Potato"], [])
    assert mapping["Potato"] != mapping["Sweet Potato"]


def test_almond_milk_does_not_merge_with_milk():
    mapping = normalizer.normalize_items(["Milk", "Almond Milk"], [])
    assert mapping["Milk"] != mapping["Almond Milk"]


def test_unripe_banana_does_not_merge_with_ripe_banana():
    mapping = normalizer.normalize_items(["Banana", "Banana Green"], [])
    assert mapping["Banana"] != mapping["Banana Green"]


def test_bottle_deposit_is_not_categorized_as_the_product_next_to_it():
    mapping = normalizer.normalize_items(["Beer", "BEER CRV"], [])
    assert mapping["Beer"] != mapping["BEER CRV"]
    assert "beer" not in mapping["BEER CRV"].lower()


# def test_unrelated_products_do_not_merge_on_spelling_similarity():
#    mapping = normalizer.normalize_items(["Britannia Bourbon", "Brioche"], [])
#    assert mapping["Britannia Bourbon"] != mapping["Brioche"]


def test_never_proposes_a_generic_placeholder_name():
    mapping = normalizer.normalize_items(["XZQ1234 SKU", "PAPER Bag"], [])
    for canonical_name in mapping.values():
        assert canonical_name.strip().lower() not in PLACEHOLDER_NAMES
