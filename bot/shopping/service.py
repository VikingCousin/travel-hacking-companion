"""Orchestrates the Shopping Optimizer: refreshes shopping_partners from
fetcher.py (upsert, so a rate change over time updates the existing row
instead of duplicating it) and finds relevant options for a user's search -
restricted to the loyalty programs they actually have in their profile.

Ranking (see docs/SHOPPING_OPTIMIZER.md, section "Ranking"): an active
promotion always wins first - that's a fair signal to compare even across
programs with different units. Below that, offers are ranked WITHIN their
own program by verified rate, never by comparing e.g. Payback points against
Miles & More miles as if they were the same currency. The result is grouped
per program so the caller can show "beste PAYBACK-Option" / "höchste
Miles & More-Rate" separately rather than implying a single cross-program
winner.
"""

import logging

from bot.db import get_connection
from bot.shopping.fetcher import fetch_all

logger = logging.getLogger(__name__)

OFFERS_PER_PROGRAM = 3


def refresh_shopping_partners() -> int:
    """Fetches every configured source and upserts into shopping_partners
    (unlike deals, a rate CAN legitimately change, so re-fetching updates
    the existing row's rate/last_verified_at rather than only inserting new
    ones). Returns how many rows were touched (inserted or updated)."""
    items = fetch_all()
    if not items:
        return 0

    conn = get_connection()
    touched = 0
    try:
        program_ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM programs")}
        for item in items:
            program_id = program_ids.get(_source_program_name(item["source"]))
            cur = conn.execute(
                """
                INSERT INTO shopping_partners
                    (loyalty_program_id, merchant, merchant_slug, category, reward_type,
                     reward_rate, reward_unit, is_promotion, promotion_text, source,
                     source_url, landing_url, last_verified_at, active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 1)
                ON CONFLICT (source, merchant_slug) DO UPDATE SET
                    category = excluded.category,
                    reward_type = excluded.reward_type,
                    reward_rate = excluded.reward_rate,
                    reward_unit = excluded.reward_unit,
                    is_promotion = excluded.is_promotion,
                    promotion_text = excluded.promotion_text,
                    landing_url = excluded.landing_url,
                    last_verified_at = datetime('now'),
                    active = 1
                """,
                (
                    program_id,
                    item["merchant"],
                    item["merchant_slug"],
                    item["category"],
                    item["reward_type"],
                    item["reward_rate"],
                    item["reward_unit"],
                    int(item["is_promotion"]),
                    item["promotion_text"],
                    item["source"],
                    item["source_url"],
                    item["landing_url"],
                ),
            )
            if cur.rowcount:
                touched += 1
        conn.commit()
    finally:
        conn.close()
    if touched:
        logger.info("Shopping partners refresh: %d row(s) touched", touched)
    return touched


def _source_program_name(source_key: str) -> str:
    from bot.shopping.sources import SOURCES

    for source in SOURCES:
        if source.key == source_key:
            return source.program_name
    return ""


def _user_loyalty_program_ids(conn, user_id: int) -> set[int]:
    rows = conn.execute(
        """
        SELECT p.id FROM card_profile cp
        JOIN programs p ON p.id = cp.program_id
        WHERE cp.user_id = ? AND p.type = 'loyalty' AND p.is_active = 1
        """,
        (user_id,),
    ).fetchall()
    return {row["id"] for row in rows}


def find_shopping_options(user_id: int, category: str) -> list[dict]:
    """Offers for `category`, restricted to the user's own loyalty programs,
    grouped per program (best offers of each program the user has, up to
    OFFERS_PER_PROGRAM each). Empty list is a valid, honest answer - never
    padded with an unrelated or unverified option."""
    conn = get_connection()
    try:
        user_program_ids = _user_loyalty_program_ids(conn, user_id)
        if not user_program_ids:
            return []
        rows = conn.execute(
            """
            SELECT sp.*, p.name AS program_name, p.emoji AS program_emoji
            FROM shopping_partners sp
            JOIN programs p ON p.id = sp.loyalty_program_id
            WHERE sp.active = 1 AND sp.category = ?
            """,
            (category,),
        ).fetchall()
    finally:
        conn.close()

    offers = [dict(row) for row in rows if row["loyalty_program_id"] in user_program_ids]
    if not offers:
        return []

    by_program: dict[int, list[dict]] = {}
    for offer in offers:
        by_program.setdefault(offer["loyalty_program_id"], []).append(offer)

    for group in by_program.values():
        group.sort(key=lambda o: (o["is_promotion"], o["reward_rate"] or -1, o["last_verified_at"]), reverse=True)

    # Cross-program order uses only a fair, unit-agnostic signal (whether a
    # program has an active promotion at all) plus a neutral tiebreak
    # (program id) - never the raw numeric rate, which would silently imply
    # e.g. Payback points and Miles & More miles are the same currency.
    ordered_program_ids = sorted(
        by_program.keys(),
        key=lambda pid: (not any(o["is_promotion"] for o in by_program[pid]), pid),
    )

    result = []
    for pid in ordered_program_ids:
        result.extend(by_program[pid][:OFFERS_PER_PROGRAM])
    return result


def estimate_reward(offer: dict, amount_eur: float) -> float | None:
    """Only ever returns a number when the offer has a verified per-euro
    rate - never estimates from a flat/conditional offer (section 10)."""
    if offer.get("reward_rate") is None:
        return None
    return round(amount_eur * offer["reward_rate"])
