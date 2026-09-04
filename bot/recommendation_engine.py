"""Pure ranking logic for /zahlen ("Womit zahlen?"). No DB or Telegram
imports here on purpose - it only turns already-fetched rows into ranked,
explainable recommendations, restricted to the cards a user actually has.
See bot/queries.py for the DB-access side (user_cards, recommendation_rules_for)
and bot/handlers/payment.py for the Telegram/UI side.
"""

from dataclasses import dataclass


@dataclass
class Recommendation:
    program_id: int
    name: str
    emoji: str | None
    reason: str
    warning: str | None
    rank: int


def recommend(user_cards, rule_rows, limit: int = 2) -> list[Recommendation]:
    """user_cards: rows/dicts with id/name/emoji - the user's own active
    card_profile entries (type='card' only, see queries.user_cards).
    rule_rows: rows/dicts with program_id/note/warning/priority, already
    filtered to the requested category/subcategory and ordered by priority
    DESC (see queries.recommendation_rules_for).

    Returns at most `limit` recommendations, highest priority first, using
    only programs present in user_cards. Empty input or no matching rule for
    any of the user's cards both correctly yield an empty list - the caller
    must not invent a fallback recommendation.

    Sorts rule_rows by priority (descending) itself rather than trusting the
    caller's ordering, so ranking is correct even if it's ever called with
    unsorted input.
    """
    cards_by_id = {c["id"]: c for c in user_cards}
    if not cards_by_id:
        return []

    sorted_rows = sorted(rule_rows, key=lambda row: row["priority"], reverse=True)

    recommendations: list[Recommendation] = []
    seen_programs: set[int] = set()
    for row in sorted_rows:
        program_id = row["program_id"]
        if program_id not in cards_by_id or program_id in seen_programs:
            continue
        seen_programs.add(program_id)
        card = cards_by_id[program_id]
        recommendations.append(
            Recommendation(
                program_id=program_id,
                name=card["name"],
                emoji=card["emoji"],
                reason=row["note"] or "",
                warning=row["warning"],
                rank=len(recommendations) + 1,
            )
        )
        if len(recommendations) >= limit:
            break
    return recommendations
