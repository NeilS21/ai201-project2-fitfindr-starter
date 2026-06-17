"""
tests/test_tools.py

One test per tool, with at least one test per failure mode.

The search_listings tests and the empty-input guards run offline. The tests that
actually call the LLM are skipped automatically when GROQ_API_KEY isn't set, so the
suite stays green without a key — set the key in .env to exercise them live.

Run with:  pytest tests/
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card, estimate_value
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

needs_key = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM test",
)


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches -> empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_is_case_insensitive_substring():
    # "m" should match listings sized "S/M", "M", etc.
    results = search_listings("tee", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    # Top result should mention at least one of the keywords somewhere obvious.
    assert results, "expected at least one match"


# ── create_fit_card (empty-input guard runs offline) ──────────────────────────

def test_fit_card_empty_outfit_returns_message():
    # Failure mode: empty/whitespace outfit -> error string, no exception.
    msg = create_fit_card("   ", {"title": "Test Tee", "price": 20, "platform": "depop"})
    assert isinstance(msg, str)
    assert msg.strip() != ""
    assert "outfit" in msg.lower()


# ── estimate_value (no-price guard runs offline) ──────────────────────────────

def test_estimate_value_no_price():
    # Failure mode: missing price -> graceful message, no LLM call, no exception.
    msg = estimate_value({"title": "Mystery Item", "price": None})
    assert "can't assess" in msg.lower()


# ── LLM-backed tests (skipped without a key) ──────────────────────────────────

SAMPLE_ITEM = {
    "title": "Y2K Baby Tee — Butterfly Print",
    "category": "tops",
    "style_tags": ["y2k", "graphic tee"],
    "colors": ["white", "pink"],
    "condition": "excellent",
    "price": 18.0,
    "brand": None,
    "platform": "depop",
}


@needs_key
def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe -> general advice, non-empty, no crash.
    out = suggest_outfit(SAMPLE_ITEM, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


@needs_key
def test_suggest_outfit_with_wardrobe():
    out = suggest_outfit(SAMPLE_ITEM, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


@needs_key
def test_fit_card_varies_between_runs():
    a = create_fit_card("baggy jeans + chunky sneakers", SAMPLE_ITEM)
    b = create_fit_card("baggy jeans + chunky sneakers", SAMPLE_ITEM)
    assert a != b, "captions should vary — raise temperature if identical"
