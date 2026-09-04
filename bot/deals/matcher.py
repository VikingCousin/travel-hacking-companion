"""Pure, transparent keyword-based relevance matching and classification for
the personal rewards feed (/deals) - no DB, no network, no LLM.

Two separate jobs:
- classify_deal(): runs ONCE per deal at ingestion time (see service.py),
  tagging it with a category/merchant/loyalty_program guess so /deals can
  group and label it without re-deriving this on every read.
- rank_deals(): runs per user per request, restricted to the programs the
  user actually has active - a deal only ever qualifies via a program match;
  preference signals (home airport, preferred airlines/alliance) can only
  ever boost the ranking of an already-qualifying deal, never invent
  relevance out of nothing.
"""

# A few real-world spelling variants seen in headlines. Centralized here so a
# new program (just a programs.name row) works out of the box, and only
# needs an entry here if its actual spelling in the wild varies.
PROGRAM_ALIASES: dict[str, list[str]] = {
    "Miles & More": ["Miles & More", "Miles&More"],
}

CATEGORY_EMOJI = {
    "shopping": "🛒",
    "miles": "✈️",
    "cards": "💳",
    "hotels": "🏨",
    "travel": "🌍",
}
CATEGORY_LABEL = {
    "shopping": "Punkte sammeln",
    "miles": "Meilen",
    "cards": "Karten",
    "hotels": "Hotels",
    "travel": "Reisen",
}
DEFAULT_CATEGORY = "travel"

# Keyword -> category. Checked in this order; first match wins. Centralized
# and easy to extend without touching any handler code.
CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hotels", ["hilton", "marriott", "bonvoy", "ihg", "accor", "hotel", "resort"]),
    ("miles", ["miles & more", "miles&more", "meile", "flying blue", "avios", "vielflieger", "airline", "flug"]),
    ("cards", ["kreditkarte", "amex", "american express", "visa", "mastercard", "willkommensbonus"]),
    ("shopping", ["payback", "edeka", " dm ", "aral", "rewe", "coupon", "punkteaktion", "händler"]),
]

# Known merchants worth calling out explicitly in the feed (7F.1 examples).
MERCHANT_KEYWORDS = ["EDEKA", "dm", "Aral", "REWE", "Rossmann", "Shell", "Esso"]


def classify_deal(title: str, summary: str | None, known_programs: list[str]) -> dict:
    """Returns {'category', 'merchant', 'loyalty_program'} for a single deal,
    from simple keyword rules only. known_programs: all programs.name values
    in the DB (cards + loyalty), used to guess which one the deal is about."""
    haystack = f"{title} {summary or ''}".lower()

    category = DEFAULT_CATEGORY
    for cat, keywords in CATEGORY_KEYWORDS:
        if any(kw in haystack for kw in keywords):
            category = cat
            break

    merchant = next((m for m in MERCHANT_KEYWORDS if m.lower() in haystack), None)

    loyalty_program = None
    for program_name in known_programs:
        if any(kw.lower() in haystack for kw in _keywords_for(program_name)):
            loyalty_program = program_name
            break

    return {"category": category, "merchant": merchant, "loyalty_program": loyalty_program}


def _keywords_for(program_name: str) -> list[str]:
    return PROGRAM_ALIASES.get(program_name, [program_name])


def match_score(
    text: str, user_programs: list[str], preference_signals: list[tuple[str, str]] | None = None
) -> tuple[int, list[str], list[str]]:
    """Returns (score, matched_program_names, matched_preference_labels).

    A deal only ever qualifies (score > 0) through a program match - a
    preference signal (e.g. home airport) can raise the score of an
    already-qualifying deal but can never make an otherwise-irrelevant deal
    appear on its own. preference_signals: list of (label, keyword)."""
    haystack = text.lower()
    matched_programs = [
        program_name
        for program_name in user_programs
        if any(keyword.lower() in haystack for keyword in _keywords_for(program_name))
    ]
    if not matched_programs:
        return 0, [], []

    matched_preferences = []
    for label, keyword in preference_signals or []:
        if keyword and keyword.lower() in haystack:
            matched_preferences.append(label)

    return len(matched_programs) + len(matched_preferences), matched_programs, matched_preferences


def rank_deals(
    deals: list[dict],
    user_programs: list[str],
    preference_signals: list[tuple[str, str]] | None = None,
    limit: int = 5,
) -> list[dict]:
    """deals: dicts with at least 'title' and 'summary'. Returns at most
    `limit` deals that matched at least one of the user's programs, each
    augmented with 'matched_programs' and 'matched_preferences', highest
    score first (ties broken by published_at, newest first). Deals matching
    nothing are dropped, not padded in - an empty result is a valid, honest
    answer."""
    scored = []
    for deal in deals:
        text = f"{deal.get('title', '')} {deal.get('summary') or ''}"
        score, matched_programs, matched_preferences = match_score(text, user_programs, preference_signals)
        if score == 0:
            continue
        scored.append(
            {**deal, "matched_programs": matched_programs, "matched_preferences": matched_preferences, "_score": score}
        )

    scored.sort(key=lambda d: (d["_score"], d.get("published_at") or ""), reverse=True)
    return scored[:limit]
