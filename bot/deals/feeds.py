"""Fetches and normalizes the public RSS/Atom feeds in sources.py. Read-only
HTTP GET against the feed URL itself - no login, no bypassing of any
protection, no HTML scraping beyond what feedparser does for a feed document.
"""

import logging
import re

import feedparser

from bot.deals.sources import DealSource

logger = logging.getLogger(__name__)

USER_AGENT = "TravelHackingCompanionBot/1.0 (+personal, non-commercial)"


def fetch_source(source: DealSource) -> list[dict]:
    """Returns normalized deal dicts for one source. Never raises - a broken
    or unreachable feed just yields an empty list (logged), so one bad
    source can't take the others down with it."""
    try:
        parsed = feedparser.parse(source.feed_url, agent=USER_AGENT)
    except Exception:
        logger.exception("Failed to fetch feed for source %s", source.key)
        return []
    return extract_items(parsed, source.key)


def extract_items(parsed, source_key: str) -> list[dict]:
    """Pure extraction step, split out from fetch_source so a malformed feed
    can be tested with an already-parsed feedparser result - no network
    needed for that test case."""
    if getattr(parsed, "bozo", False) and not parsed.entries:
        logger.warning("Feed for %s looks broken (bozo) and has no entries - skipping", source_key)
        return []

    items = []
    for entry in parsed.entries:
        external_id = entry.get("id") or entry.get("link")
        url = entry.get("link")
        title = (entry.get("title") or "").strip()
        if not external_id or not url or not title:
            continue
        items.append(
            {
                "source": source_key,
                "external_id": external_id,
                "title": title,
                "url": url,
                "summary": _clean_summary(entry.get("summary")),
                "published_at": entry.get("published") or entry.get("updated"),
            }
        )
    return items


def _clean_summary(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:400] if text else None
