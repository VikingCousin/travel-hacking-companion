"""Transparent keyword/alias matching for the Shopping Optimizer - no LLM.
Maps free text the user types (e.g. "Schuhe") to one of a small set of
canonical categories that shopping_partners rows are tagged with. Case-
insensitive substring matching only; a query matching nothing returns None,
which the handler turns into an honest "not recognized" message rather than
guessing.
"""

CATEGORY_LABELS: dict[str, str] = {
    "fashion": "👟 Mode & Schuhe",
    "electronics": "💻 Elektronik",
    "drugstore": "🧴 Drogerie",
    "supermarket": "🛒 Supermarkt",
    "travel": "🌍 Reisen",
    "hotel": "🏨 Hotel",
    "rental_car": "🚗 Mietwagen",
}

# canonical category -> keywords that map free text to it. Extend this list
# rather than adding special-case code elsewhere.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "fashion": ["schuh", "sneaker", "stiefel", "bekleidung", "kleidung", "klamotten", "mode", "fashion", "apparel", "koffer", "gepäck", "hose", "jacke"],
    "electronics": ["elektronik", "electronics", "laptop", "notebook", "computer", "pc", "handy", "smartphone", "kamera", "fernseher", "tv"],
    "drugstore": ["drogerie", "drugstore", "shampoo", "kosmetik", "beauty", "pflege", "hygiene"],
    "supermarket": ["supermarkt", "supermarket", "lebensmittel", "einkauf"],
    "travel": ["reise", "reisen", "travel", "flug", "urlaub", "trip"],
    "hotel": ["hotel", "übernachtung", "unterkunft"],
    "rental_car": ["mietwagen", "autovermietung", "rental car", "leihwagen"],
}


def normalize(text: str) -> str:
    return text.strip().lower()


def match_category(user_input: str) -> str | None:
    """Returns the canonical category key for a free-text query, or None if
    nothing matches - callers must not guess a category in that case."""
    haystack = normalize(user_input)
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return category
    return None
