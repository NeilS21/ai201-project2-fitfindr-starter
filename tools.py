"""
tools.py

The FitFindr tools. Each tool is a standalone function that can be called and
tested on its own before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  -> list[dict]
    suggest_outfit(new_item, wardrobe)             -> str
    create_fit_card(outfit, new_item)              -> str
    estimate_value(item)                           -> str   (stretch)
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(prompt: str, temperature: float = 0.7) -> str:
    """Send a single user prompt to the LLM and return the text response."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings for items matching the description, with optional
    size and price filters. Returns matches sorted by relevance (best first),
    or an empty list if nothing matches. Never raises.

    See planning.md (Tool 1) for the full spec.
    """
    listings = load_listings()

    # Pull the description apart into lowercase keyword tokens.
    keywords = [w for w in re.findall(r"[a-z0-9]+", description.lower()) if len(w) > 1]

    scored = []
    for item in listings:
        # Price filter (inclusive).
        if max_price is not None and item.get("price") is not None:
            if item["price"] > max_price:
                continue

        # Size filter — case-insensitive substring so "M" matches "S/M".
        if size:
            item_size = (item.get("size") or "").lower()
            if size.lower() not in item_size:
                continue

        # Score by how many description keywords show up in the item's text.
        haystack = " ".join([
            item.get("title", ""),
            item.get("description", ""),
            item.get("category", ""),
            " ".join(item.get("style_tags", [])),
            " ".join(item.get("colors", [])),
            str(item.get("brand") or ""),
        ]).lower()

        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scored.append((score, item))

    # Best match first.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Suggest 1-2 complete outfits built around new_item using the user's wardrobe.
    Falls back to general styling advice when the wardrobe is empty. Returns a
    non-empty string; catches LLM errors and returns a plain fallback instead of
    crashing.

    See planning.md (Tool 2) for the full spec.
    """
    item_line = (
        f"{new_item.get('title', 'this item')} "
        f"({new_item.get('category', 'item')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe -> general advice instead of failing.
        prompt = (
            f"A shopper is considering this secondhand piece: {item_line}.\n"
            "They haven't told us anything they already own. Give 1-2 short, "
            "practical outfit ideas: what kinds of pieces pair well with it, what "
            "vibe it suits, and how to style it. Keep it friendly and concise."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'item')} ({it.get('category', '')}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            f"A shopper is considering this secondhand piece: {item_line}.\n\n"
            f"Here is what they already own:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits built around the new piece, naming "
            "specific items from their wardrobe by name. Keep it concise and "
            "practical, like a friend giving styling advice."
        )

    try:
        return _chat(prompt, temperature=0.7)
    except Exception as exc:  # network/key/etc — degrade, don't crash
        return (
            f"Couldn't reach the styling assistant ({exc}). "
            f"As a starting point, {new_item.get('title', 'this piece')} works well "
            "with simple, neutral basics that let it stand out."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, casual, shareable caption for the thrifted find. Guards
    against an empty outfit string (returns an error message, never raises), and
    runs at a higher temperature so it reads differently each time.

    See planning.md (Tool 3) for the full spec.
    """
    if not outfit or not outfit.strip():
        return "Can't make a fit card without an outfit suggestion to work from."

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    price_str = f"${price:g}" if price is not None else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        f"Write a short, casual outfit caption (2-4 sentences) for a thrifted find, "
        f"like a real OOTD post — not a product description.\n\n"
        f"Item: {title}\nPrice: {price_str}\nPlatform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        f"Mention the item name, price, and platform once each, naturally. Capture "
        f"the vibe in specific terms. Keep it authentic and a little playful."
    )

    try:
        return _chat(prompt, temperature=0.95)
    except Exception:
        # Simple template fallback so the user still gets something usable.
        return (
            f"thrifted this {title} off {platform} for {price_str} and i'm obsessed. "
            f"styled it up like: {outfit}"
        )


# ── Tool 4: estimate_value (stretch) ──────────────────────────────────────────

def estimate_value(item: dict) -> str:
    """
    Quick read on whether the asking price is fair for the item's condition,
    brand, category, and platform. Informational only — never blocks the flow.

    See planning.md (Tool 4) for the full spec.
    """
    price = item.get("price")
    if price is None:
        return "Can't assess — no price listed."

    prompt = (
        "You're a savvy thrift shopper. In one short sentence, say whether this "
        "price looks fair, give a quick verdict word (Steal / Fair / Steep), and a "
        "one-line reason.\n\n"
        f"Item: {item.get('title', 'item')}\n"
        f"Category: {item.get('category', 'n/a')}\n"
        f"Condition: {item.get('condition', 'n/a')}\n"
        f"Brand: {item.get('brand') or 'unbranded'}\n"
        f"Platform: {item.get('platform', 'n/a')}\n"
        f"Price: ${price:g}"
    )

    try:
        return _chat(prompt, temperature=0.3)
    except Exception:
        return "Price check unavailable."
