def parse_amount(text: str) -> int | None:
    """Parses formats like '8450', '8.450', '8 450'. Rejects negative values
    and anything non-numeric by returning None."""
    cleaned = text.strip().replace(" ", "").replace(".", "").replace(",", "")
    if not cleaned or not cleaned.isdigit():
        return None
    return int(cleaned)


def format_amount(value: int) -> str:
    """1000er-Trennzeichen im deutschen Format: 8450 -> '8.450'."""
    return f"{value:,}".replace(",", ".")


def is_safe_url(url: str | None) -> bool:
    """Telegram itself rejects a non-http(s) scheme on an inline URL button
    server-side, but every place that builds one from external data (an RSS
    feed's own <link>, a scraped source_url/landing_url) checks this first
    anyway (Phase 7L) - so a malformed or unexpected scheme fails with our
    own graceful fallback instead of an unhandled BadRequest reaching the
    generic error handler."""
    if not url:
        return False
    return url.strip().lower().startswith(("https://", "http://"))
