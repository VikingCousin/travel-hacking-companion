"""Orchestrates the personal rewards feed: fetches configured sources into
the `deals` table (deduplicated via UNIQUE(source, external_id)), classifies
each new deal once at ingestion (matcher.classify_deal), and computes
per-user relevant deals via matcher.rank_deals - restricted to the programs
and preferences the user actually has. Also tracks which deals a user has
already seen (user_deal_notifications) so /deals and the daily digest can
never show or send the same deal to the same user twice."""

import logging

from bot.db import get_connection
from bot.deals.feeds import fetch_source
from bot.deals.matcher import classify_deal, rank_deals
from bot.deals.sources import SOURCES

logger = logging.getLogger(__name__)

DEAL_POOL_SIZE = 200  # how many recent deals to consider when ranking
SOURCE_CONFIDENCE = "public_rss"  # all current sources are public blog/RSS feeds

DEAL_COLUMNS = "id, source, title, url, summary, published_at, category, merchant, loyalty_program"


def refresh_all_sources() -> int:
    """Fetches every configured source and stores newly-seen deals,
    classifying each one once at insert time. Safe to call repeatedly -
    re-fetching the same feed just no-ops on already-known items. Returns how
    many new deals were actually inserted. One broken source never blocks the
    others (see feeds.fetch_source)."""
    conn = get_connection()
    inserted = 0
    try:
        known_programs = [row["name"] for row in conn.execute("SELECT name FROM programs")]
        for source in SOURCES:
            items = fetch_source(source)
            for item in items:
                tags = classify_deal(item["title"], item["summary"], known_programs)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO deals
                        (source, external_id, title, url, summary, published_at,
                         category, merchant, loyalty_program, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["source"],
                        item["external_id"],
                        item["title"],
                        item["url"],
                        item["summary"],
                        item["published_at"],
                        tags["category"],
                        tags["merchant"],
                        tags["loyalty_program"],
                        SOURCE_CONFIDENCE,
                    ),
                )
                if cur.rowcount:
                    inserted += 1
        conn.commit()
    finally:
        conn.close()
    if inserted:
        logger.info("Deal refresh: %d new deal(s) stored", inserted)
    return inserted


def _user_program_names(conn, user_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT p.name FROM card_profile cp
        JOIN programs p ON p.id = cp.program_id
        WHERE cp.user_id = ?
        """,
        (user_id,),
    ).fetchall()
    return [row["name"] for row in rows]


def _preference_signals(conn, user_id: int) -> list[tuple[str, str]]:
    """(label, keyword) pairs used as ranking-boost-only signals in
    matcher.rank_deals - never as a standalone qualifier. Imports the
    alliance label map from bot.handlers.preferences, the single source of
    truth for that enum (same pattern already used by bot/handlers/status.py)."""
    from bot.handlers.preferences import ALLIANCE_LABELS

    row = conn.execute(
        "SELECT home_airport, preferred_airlines, preferred_alliance FROM user_preferences WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return []

    signals = []
    if row["home_airport"]:
        signals.append((f"Heimatflughafen {row['home_airport']}", row["home_airport"]))
    if row["preferred_airlines"]:
        for airline in row["preferred_airlines"].split(","):
            airline = airline.strip()
            if airline:
                signals.append((airline, airline))
    if row["preferred_alliance"] and row["preferred_alliance"] != "none":
        label = ALLIANCE_LABELS.get(row["preferred_alliance"])
        if label:
            signals.append((label, label.split(maxsplit=1)[-1] if " " in label else label))
    return signals


def _fetch_deal_pool(conn, user_id: int, only_unnotified: bool) -> list[dict]:
    if only_unnotified:
        query = f"""
            SELECT {DEAL_COLUMNS} FROM deals
            WHERE id NOT IN (SELECT deal_id FROM user_deal_notifications WHERE user_id = ?)
            ORDER BY fetched_at DESC LIMIT ?
        """
        params = (user_id, DEAL_POOL_SIZE)
    else:
        query = f"SELECT {DEAL_COLUMNS} FROM deals ORDER BY fetched_at DESC LIMIT ?"
        params = (DEAL_POOL_SIZE,)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def relevant_deals_for_user(user_id: int, limit: int = 5, offset: int = 0) -> list[dict]:
    """The user's current top relevant deals, freshest among ties. Always
    considers all stored deals regardless of prior notification status -
    voluntarily viewing /deals is not the same as an unsolicited alert.
    `offset` supports the "mehr anzeigen" pagination in the /deals UI."""
    conn = get_connection()
    try:
        user_programs = _user_program_names(conn, user_id)
        if not user_programs:
            return []
        preference_signals = _preference_signals(conn, user_id)
        deals = _fetch_deal_pool(conn, user_id, only_unnotified=False)
    finally:
        conn.close()
    ranked = rank_deals(deals, user_programs, preference_signals, limit=limit + offset)
    return ranked[offset:]


def find_new_relevant_deals_for_alerting(user_id: int, limit: int = 5) -> list[dict]:
    """Relevant deals the user has NOT already been notified about (per
    user_deal_notifications). Used by both the daily digest job and, if
    called directly, an ad-hoc "what's new" check."""
    conn = get_connection()
    try:
        user_programs = _user_program_names(conn, user_id)
        if not user_programs:
            return []
        preference_signals = _preference_signals(conn, user_id)
        deals = _fetch_deal_pool(conn, user_id, only_unnotified=True)
    finally:
        conn.close()
    return rank_deals(deals, user_programs, preference_signals, limit=limit)


def mark_deals_notified(user_id: int, deal_ids: list[int]) -> None:
    """Records that these deals have been shown to this user (via /deals or
    the daily digest), so they're excluded from future
    find_new_relevant_deals_for_alerting results. Idempotent - safe to call
    with deals already marked."""
    if not deal_ids:
        return
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO user_deal_notifications (user_id, deal_id) VALUES (?, ?)",
            [(user_id, deal_id) for deal_id in deal_ids],
        )
        conn.commit()
    finally:
        conn.close()


def all_user_ids(conn=None) -> list[int]:
    """Every registered user (has run /start at least once) - used by the
    daily digest job to know who to consider."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        return [row["telegram_id"] for row in conn.execute("SELECT telegram_id FROM users")]
    finally:
        if owns_conn:
            conn.close()
