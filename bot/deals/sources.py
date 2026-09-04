"""Registry of public deal sources for /deals. Only sites with a verified,
stable public RSS/Atom feed are listed - per the project rule against
fragile HTML scraping, anything without one is left out on purpose rather
than forced (see docs/OVERNIGHT_REPORT.md for the sources considered).

Feed URLs verified manually before wiring this up:
- reisetopia.de/feed/          -> valid RSS 2.0 (the www. subdomain 403s;
                                   the bare domain works, so that's used)
- travel-dealz.de/feed/        -> valid RSS 2.0
- meilenoptimieren.de/feed/    -> 301-redirects to meilenoptimieren.com/feed/,
                                   itself a valid RSS 2.0 feed - configured
                                   directly here to skip the extra redirect
                                   hop on every fetch.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DealSource:
    key: str
    name: str
    feed_url: str


SOURCES = [
    DealSource("reisetopia", "reisetopia.de", "https://reisetopia.de/feed/"),
    DealSource("travel-dealz", "travel-dealz.de", "https://travel-dealz.de/feed/"),
    DealSource("meilenoptimieren", "meilenoptimieren.de", "https://meilenoptimieren.com/feed/"),
]
