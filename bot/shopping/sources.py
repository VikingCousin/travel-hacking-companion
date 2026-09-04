"""Registry of shopping-rewards sources for the Shopping Optimizer.

Investigated before writing any fetch code (see docs/SHOPPING_OPTIMIZER.md
for the full writeup):

- payback.de/online-shopping: server-side rendered HTML (Next.js/MUI),
  robots.txt does not disallow it, content is a small curated "featured
  partners" list with visible point rates. A small, defensive regex parser
  is justified here (see fetcher.py) - not a full scraper of PAYBACK's
  entire catalog, just this one public landing page.
- miles-and-more.com: blocked outright (HTTP 403 on every path tried,
  including the bare domain) by bot protection. Not worked around -
  bypassing that would cross into "Umgehung technischer Schutzmaßnahmen",
  which is explicitly out of scope. No Miles & More shopping-portal source
  exists in this project as a result; documented, not forced.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShoppingSource:
    key: str
    program_name: str  # which programs.name this source's rates belong to
    url: str


SOURCES = [
    ShoppingSource("payback_online_shopping", "Payback", "https://www.payback.de/online-shopping"),
]
