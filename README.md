# FitFindr 🛍️

FitFindr is a multi-tool AI agent that helps you find secondhand clothing and figure
out how to wear it. You describe what you're after in plain language ("vintage graphic
tee under $30"), and the agent searches a set of mock listings, checks whether the
price looks fair, suggests outfits using pieces you already own, and writes a casual
caption you could actually post.

The interesting part isn't the individual tools — it's the **planning loop** that
decides which tool to call and when, the **session state** that carries information
from one tool to the next, and the **error handling** that keeps the agent useful when
a search comes back empty or a tool can't do its job.

![FitFindr walkthrough](walkthrough.gif)

---

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash); use .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in the project root (it's already in
`.gitignore`, so it won't be committed):

```
GROQ_API_KEY=gsk_your_key_here
```

Run the web app:

```bash
python app.py
```

Then open the URL shown in your terminal (usually http://localhost:7860). You can also
run the agent from the command line with `python agent.py`, or the tool tests with
`pytest tests/`.

---

## Tool Inventory

The agent uses four tools. The first three are the required ones; `estimate_value` is a
stretch tool I added. These signatures match `tools.py` exactly.

### `search_listings(description, size, max_price) -> list[dict]`
- **Inputs:**
  - `description` (`str`) — keywords for what the user wants, e.g. `"vintage graphic tee"`.
  - `size` (`str | None`) — size filter, matched case-insensitively as a substring so `"M"` matches a listing sized `"S/M"`. `None` skips the filter.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips the filter.
- **Output:** a list of listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted best-match first. Empty list if nothing matches.
- **Purpose:** find candidate items. Filters out anything too expensive or the wrong size, then scores what's left by keyword overlap with the description and drops zero-score items.

### `suggest_outfit(new_item, wardrobe) -> str`
- **Inputs:**
  - `new_item` (`dict`) — the selected listing.
  - `wardrobe` (`dict`) — has an `"items"` key listing the user's pieces. Can be empty.
- **Output:** a non-empty string with 1–2 outfit ideas. Names real wardrobe pieces when the wardrobe has items; gives general styling advice when it's empty.
- **Purpose:** figure out how the found item fits with what the user already owns. This is an LLM call (Groq `llama-3.3-70b-versatile`).

### `create_fit_card(outfit, new_item) -> str`
- **Inputs:**
  - `outfit` (`str`) — the suggestion string from `suggest_outfit()`.
  - `new_item` (`dict`) — the selected listing (for name, price, platform).
- **Output:** a 2–4 sentence casual caption that mentions the item, price, and platform once each. Runs at a high temperature so it reads differently each time.
- **Purpose:** turn the outfit into something shareable, like an OOTD post. LLM call.

### `estimate_value(item) -> str` (stretch)
- **Inputs:** `item` (`dict`) — a listing.
- **Output:** a short verdict string (Steal / Fair / Steep) with a one-line reason.
- **Purpose:** quick gut-check on whether the price is fair. Informational only — it never changes what the agent does next. LLM call.

---

## How the Planning Loop Works

`run_agent(query, wardrobe)` in `agent.py` runs the loop for one interaction. It isn't a
fixed pipeline — what it does depends on what each step returns. The whole thing is
driven by a single `session` dict.

1. **Parse the query.** `_parse_query()` asks the LLM to return JSON with `description`,
   `size`, and `max_price`. I chose the LLM over regex because people phrase size and
   price a lot of different ways ("size medium", "M", "under thirty bucks"). If the LLM
   call fails or the JSON won't parse, it falls back to using the whole query as the
   description with no filters.
2. **Search.** Calls `search_listings()` with the parsed parameters. **This is the one
   real branch:** if the result is an empty list, the loop sets a specific error message
   on the session and **returns early** — it does *not* call `suggest_outfit` with an
   empty item. If there are matches, it continues.
3. **Select** the top-ranked result as `selected_item`.
4. **Estimate value** (stretch) on the selected item. Informational, never branches.
5. **Suggest an outfit** using the selected item and the wardrobe.
6. **Create the fit card** from the outfit suggestion and the item.
7. **Return** the session.

The key behavior: the agent **responds differently to different inputs**. A query that
matches runs all the tools; an impossible query stops at step 2 and explains itself.

## State Management

Everything for one interaction lives in a single `session` dict created by
`_new_session()`. Each step reads the fields it needs and writes its result back, so the
user never re-enters anything — the item `search_listings` finds flows straight into
`suggest_outfit`, and that suggestion flows into `create_fit_card`.

| Field | Written by | Read by |
|-------|-----------|---------|
| `query` | `_new_session` | parse step |
| `parsed` | parse step | search step |
| `search_results` | `search_listings` | select step / empty check |
| `selected_item` | select step | `estimate_value`, `suggest_outfit`, `create_fit_card` |
| `value_estimate` | `estimate_value` | UI listing panel |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card`, UI |
| `fit_card` | `create_fit_card` | UI |
| `error` | whatever step stops early | checked first by the caller |

The caller (`agent.py`'s CLI block, or `handle_query()` in `app.py`) checks
`session["error"]` first. If it's set, the other output fields are `None` and the error
is shown instead.

---

## Error Handling and Fail Points

Every tool handles its own failure mode and returns a useful value instead of raising.
The examples below are real output I got while triggering each failure deliberately.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listings match | Returns `[]`; the loop sets an error and stops before `suggest_outfit`. |
| `suggest_outfit` | Wardrobe is empty | Switches to a general-advice prompt and still returns a real string. |
| `create_fit_card` | Outfit string is empty | Returns a descriptive message instead of crashing. |
| `estimate_value` | No price on the item | Returns a graceful message; never blocks the flow. |

**Concrete examples from testing:**

- **`search_listings` empty (full agent):** running the agent on `"designer ballgown
  size XXS under $5"` set
  `session["error"] = 'No matches for "designer ballgown" in size XXS under $5. Try
  loosening a filter — a higher price, a different size, or broader keywords.'`
  and left `session["fit_card"]` as `None`. `suggest_outfit` was never called.
- **`create_fit_card` empty outfit:** `create_fit_card("", item)` returned
  `"Can't make a fit card without an outfit suggestion to work from."` — a string, not
  an exception.
- **`suggest_outfit` empty wardrobe:** with `get_empty_wardrobe()`, it returned general
  styling advice ("Pair it with high-waisted jeans and sneakers for a casual, retro
  vibe…") instead of an empty string.
- **`estimate_value` no price:** `estimate_value({"price": None})` returned
  `"Can't assess — no price listed."` without making an LLM call.

The LLM-backed tools also wrap their API calls in `try/except`, so a network or key
problem degrades to a plain fallback string rather than crashing the agent.

---

## Interaction Walkthrough

**User query:** "I'm looking for a vintage graphic tee under $30."

**Step 1 — `_parse_query`**
- Why: turn the sentence into search parameters.
- Output: `{"description": "vintage graphic tee", "size": null, "max_price": 30.0}`.

**Step 2 — `search_listings("vintage graphic tee", None, 30.0)`**
- Why: find candidate items inside the price ceiling.
- Output: a ranked list; the top hit is the **Y2K Baby Tee — Butterfly Print, $18,
  Depop** (`id = lst_002`). Not empty, so the loop continues.

**Step 3 — select + `estimate_value`**
- The top result becomes `selected_item`. `estimate_value` returns roughly "Fair — $18
  is reasonable for an excellent-condition Y2K tee on Depop."

**Step 4 — `suggest_outfit(selected_item, wardrobe)`**
- Why: style the item against what the user owns. The *same* `selected_item` dict from
  step 2 is passed in — this is the visible state hand-off.
- Output: "Pair it with your baggy straight-leg jeans and chunky white sneakers… or your
  wide-leg khaki trousers and black combat boots."

**Step 5 — `create_fit_card(outfit_suggestion, selected_item)`**
- Why: turn the suggestion into a caption. The `outfit_suggestion` string from step 4
  feeds straight in.
- Output: "Just scored this adorable Y2K Baby Tee on Depop for $18… pairing it with my
  baggy jeans and chunky sneakers for major early-2000s vibes."

**Final output to user:** three panels — the listing (with the value read), the outfit
idea, and the fit card. `session["error"]` is `None`.

---

## How I Used AI

I used **Claude (via Claude Code)** as a coding tool, but I drove it with the spec I had
already written in `planning.md` — I gave it one piece at a time and reviewed everything
against my spec before keeping it. Two specific instances:

**1. Implementing `search_listings`.**
I directed it by pasting in the Tool 1 block from `planning.md` (the inputs, the return
contents, and the "returns `[]`, never raises" failure mode) plus the `load_listings()`
docstring, and asked it to implement just that one function. It came back with a version
that filtered by price and size and scored matches by keyword overlap. **What I revised:**
its first scoring only looked at the listing title, which missed obvious matches. I
changed it to score against the title, description, style_tags, colors, and brand
together, and made sure it drops any listing that scores zero so unrelated items don't
leak through. I then tested it with three queries (a normal match, a price filter, and
the impossible-query empty case) before trusting it.

**2. Implementing the planning loop.**
I directed it with the Planning Loop and State Management sections plus the Mermaid
diagram from `planning.md`, and asked it to implement `run_agent()`. The thing I checked
hardest was the branch — does it actually return early when `search_listings` comes back
empty, instead of calling all the tools every time? **What I revised:** I rewrote the
no-results error message to be *actionable* ("try loosening a filter — a higher price, a
different size, or broader keywords") instead of the generic "no results found" it
generated. **Something I could have revised but chose to keep:** it placed my stretch
`estimate_value` call as a purely informational step that doesn't affect the branch. I'd
originally considered letting the value estimate influence which item gets selected, but
I decided the AI's simpler version was actually the better design (one clean branch is
easier to reason about and test), so I kept it. I verified state was really flowing by
printing `selected_item` and confirming it was the same dict passed into `suggest_outfit`.

---

## Spec Reflection

**One way `planning.md` helped during implementation:**
Writing the State Management table and the agent diagram first meant the planning loop
was almost a transcription job — I already knew the exact session field names and the
order tools fire in, and the diagram made the single empty-search branch obvious. When I
prompted the AI tool, I could hand it a precise spec instead of a vague "build an agent,"
which made the generated code match what I actually wanted on the first try.

**One divergence from my spec, and why:**
In planning I floated the idea of letting `estimate_value` influence which item gets
selected. While implementing, I kept it purely informational instead. Letting it change
the selection would have added a second branch and made the loop harder to reason about
and test, and the value read is more useful as a "by the way, this price is fair" note
in the UI than as a hidden filter. Keeping the one clean branch (empty vs. non-empty
search) made the agent's behavior easier to explain and verify.
