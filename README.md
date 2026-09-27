# Travel Hacking Companion

A personal Telegram bot that helps a small group of users (myself and family) track credit-card and loyalty-program points, get a transparent recommendation on which card to use for a purchase, and see relevant public reward promotions — without ever touching a real bank, card, or loyalty-program login.

## Why this exists

"Travel hacking" (optimizing credit-card rewards, airline miles, and loyalty points to travel more for less) works best when you actually track what you have and know which card to reach for. Spreadsheets are tedious and nobody opens them. This project turns that tracking and decision-making into a few Telegram commands, built as a personal automation project and a hands-on exercise in AI-assisted software development (built with Claude Code).

## What it does

- **Multi-user, with access control** — an admin allowlist bootstraps the bot; anyone else can request access via an in-chat approval flow, and each user's data is fully isolated.
- **`/profil`** — a hub for managing payment cards, loyalty programs (including custom ones you add yourself, not just a fixed catalog), travel preferences, and goals.
- **`/status`** — a compact personal dashboard: point balances, active goal progress, setup summary.
- **`/punkte` / `/ziele`** — manually track point balances and set a savings goal (e.g. "40,000 miles for a business-class flight"), with progress shown as a bar.
- **`/zahlen` ("which card should I use?")** — a rule-based recommendation engine that only ever suggests cards you actually have, with a plain-language reason for each suggestion. No black box, no LLM guessing, no invented cashback numbers — if a rule isn't backed by a verified rate, the bot says so instead of making one up.
- **`/deals`** — a personalized feed of public travel-deal articles (parsed from a few travel-hacking blogs' RSS feeds), matched to your own cards/programs by keyword, plus an optional daily digest that only fires when there's something genuinely new for you.
- **`/shopping`** ("where should I start this purchase to earn the most?") — looks up verified shopping-portal reward rates (currently Payback's public partner page) for a category you type in, grouped by loyalty program so miles and points are never mixed into one fake number.

## What it deliberately does *not* do

No login to any bank, card, or loyalty account. No scraping behind a login wall. No browser automation. No LLM-based classification (every recommendation is a transparent, inspectable rule). No invented reward rates or promotions — if a number can't be verified from a real, currently-checked public source, the bot says so rather than guessing.

## Tech stack

- Python 3.13, [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) (async, with its JobQueue for scheduled jobs)
- SQLite, with schema changes always applied as additive, idempotent migrations (existing user data is never dropped)
- [feedparser](https://feedparser.readthedocs.io/) for the public RSS deal feeds
- Plain `urllib` + a small, defensive regex parser for the one shopping-partner page that's server-rendered and robots.txt-permitted (no fragile scraping of sources that don't offer a stable, public, machine-readable interface)

## Architecture

```
bot/
  handlers/     Telegram-facing layer — one module per feature (profile, points,
                goals, payment, shopping, deals, access, ...)
  deals/        Public deal feeds: fetch → classify → rank → digest
  shopping/     Shopping-reward sources: fetch → categorize → rank
  recommendation_engine.py   Pure card-ranking logic, no DB/Telegram dependency
  queries.py    Shared DB access helpers
  db.py         Schema + additive migrations
```

Handlers stay thin; the actual ranking/matching logic lives in small, pure, independently-testable modules. Every recommendation-producing module returns an empty result rather than guessing when it doesn't have verified data for a given case.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `BOT_TOKEN` — from [@BotFather](https://t.me/BotFather) (`/newbot`)
- `ALLOWED_USER_IDS` — your Telegram user ID(s) as the admin bootstrap, comma-separated (from [@userinfobot](https://t.me/userinfobot)). Everyone else goes through the in-chat access-request flow, not `.env`.

## Run

```bash
source .venv/bin/activate
python -m bot.main
```

## Tests

No test-framework dependency — plain scripts, each runnable directly:

```bash
source .venv/bin/activate
python tests/test_regression.py
python tests/test_db_migration.py
python tests/test_routing.py
python tests/test_rewards_feed.py
python tests/test_access_and_security.py
python tests/test_shopping_optimizer.py
python tests/test_custom_programs.py
python tests/test_menu_routing_regression.py
```

Details on what each file covers: [tests/README.md](tests/README.md)

## Project status

Personal / beta project, currently running for a small private group of users (not publicly deployed). Actively evolving — see `docs/` for the development history and known limitations of individual features (e.g. only one shopping-rewards source is currently connected; a couple of loyalty programs mentioned in the code have no live promotion data yet, by design, rather than guessed).

## Docs

- [`docs/OVERNIGHT_REPORT.md`](docs/OVERNIGHT_REPORT.md) / [`docs/PHASE7_REPORT.md`](docs/PHASE7_REPORT.md) — development history and QA notes
- [`docs/SHOPPING_OPTIMIZER.md`](docs/SHOPPING_OPTIMIZER.md) — sources, ranking logic, and known limitations of the shopping optimizer
- [`docs/FUTURE_MONETIZATION.md`](docs/FUTURE_MONETIZATION.md) — a non-implemented sketch of how access control could later separate from a subscription model
- [`docs/BRANDING.md`](docs/BRANDING.md) — naming/branding notes
