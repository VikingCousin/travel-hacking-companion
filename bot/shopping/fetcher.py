"""Fetches and defensively parses shopping_partners data from the sources in
sources.py. Never raises - a source that's unreachable or whose page
structure has changed just yields an empty list (logged), so callers can
show "temporarily unavailable" instead of crashing or lying about freshness.

Only the PAYBACK featured-partners landing page is fetched here (see
sources.py for why Miles & More has none). This is a small, targeted parser
for one specific, server-rendered page - not a general-purpose scraper.
"""

import logging
import re
import urllib.error
import urllib.request

from bot.shopping.sources import SOURCES, ShoppingSource

logger = logging.getLogger(__name__)

USER_AGENT = "TravelHackingCompanionBot/1.0 (+personal, non-commercial)"
REQUEST_TIMEOUT = 15

# A handful of shop-name -> category mappings for merchants known to appear
# on the PAYBACK featured page, matched case-insensitively against the
# merchant name. Deliberately conservative: a merchant not listed here
# simply gets category=None (still stored, just not matchable by category -
# e.g. an insurance broker doesn't fit any of our shopping categories, and
# forcing one would be a wrong guess, not a convenience).
MERCHANT_CATEGORY: dict[str, str] = {
    "emp": "fashion",
    "baur": "fashion",
    "dm": "drugstore",
    "sunexpress online": "travel",
    "jochen schweizer": "travel",
}

# "1 °P pro 2 €" -> 0.5 points per euro. Only this exact "N °<unit> pro M €"
# shape is treated as a clean per-euro rate; "pro Buchung"/"pro Abo"/"bis zu"
# style offers are NOT numeric per-euro rates and must not be forced into one.
_RATE_PER_EURO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*°?P\s*pro\s*(\d+(?:[.,]\d+)?)\s*€\s*$", re.I)

# One PAYBACK "shop tile": a link to /shop/<slug> with an aria-label (the
# shop name), followed by two <p> tags - the second one is the rate text.
# Matches the real, inspected page structure; if PAYBACK changes their
# markup this simply stops matching (findall returns []), it never raises.
_TILE_PATTERN = re.compile(
    r'href="(https://www\.payback\.de/shop/[a-zA-Z0-9_-]+)"[^>]{0,200}?aria-label="([^"]{1,80})"'
    r'.{0,400}?<p class="[^"]*">[^<]*</p><p class="[^"]*">([^<]{1,60})</p>',
    re.S,
)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_rate(rate_text: str) -> tuple[float | None, bool]:
    """Returns (points_per_euro or None, looks_like_a_promotion_guess). The
    promotion guess is intentionally always False here - this landing page
    doesn't reliably distinguish "always-on partner rate" from "time-limited
    promotion", so we don't claim either (see docs/SHOPPING_OPTIMIZER.md)."""
    match = _RATE_PER_EURO.match(rate_text)
    if not match:
        return None, False
    numerator = float(match.group(1).replace(",", "."))
    denominator = float(match.group(2).replace(",", "."))
    if denominator == 0:
        return None, False
    return numerator / denominator, False


def fetch_source(source: ShoppingSource) -> list[dict]:
    """Returns normalized shopping_partners dicts for one source. Never
    raises - network errors, timeouts, and unparseable pages all just
    produce an empty list (logged)."""
    try:
        req = urllib.request.Request(source.url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.exception("Failed to fetch shopping source %s", source.key)
        return []

    try:
        matches = _TILE_PATTERN.findall(html)
    except Exception:
        logger.exception("Failed to parse shopping source %s", source.key)
        return []

    items = []
    seen_slugs = set()
    for landing_url, merchant, rate_text in matches:
        merchant = merchant.strip()
        slug = _slugify(merchant)
        if not merchant or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        rate, is_promotion = _parse_rate(rate_text.strip())
        items.append(
            {
                "source": source.key,
                "merchant": merchant,
                "merchant_slug": slug,
                "category": MERCHANT_CATEGORY.get(merchant.lower()),
                "reward_type": "points_per_euro" if rate is not None else "conditional",
                "reward_rate": rate,
                "reward_unit": "Punkte",
                "is_promotion": is_promotion,
                "promotion_text": rate_text.strip(),
                "source_url": source.url,
                "landing_url": landing_url,
            }
        )

    if not items:
        logger.warning("Shopping source %s yielded no parseable partners - page structure may have changed", source.key)
    return items


def fetch_all() -> list[dict]:
    all_items = []
    for source in SOURCES:
        all_items.extend(fetch_source(source))
    return all_items
