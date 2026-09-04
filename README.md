# Travel Hacking Companion Bot

Telegram-Bot für Payback/Miles & More/Kreditkarten-Punkte-Tracking, regelbasierten Card-Recommender, einen personalisierten Rewards-/Deal-Feed und einen Shopping-Optimizer. Multi-User mit Access-Request-System, SQLite, keine Logins/Scraping bei Bank- oder Loyalty-Konten.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` ausfüllen:
- `BOT_TOKEN`: von [@BotFather](https://t.me/BotFather) (`/newbot`)
- `ALLOWED_USER_IDS`: deine Telegram-User-ID(s) als Admin-Bootstrap, kommagetrennt (von [@userinfobot](https://t.me/userinfobot)). Weitere Nutzer laufen über das Access-Request-System (`/start` → "Zugang anfragen" → Admin-Freigabe), nicht über `.env`.

## Starten

```bash
source .venv/bin/activate
python -m bot.main
```

## Tests

```bash
source .venv/bin/activate
python tests/test_regression.py
python tests/test_db_migration.py
python tests/test_routing.py
python tests/test_rewards_feed.py
python tests/test_access_and_security.py
python tests/test_shopping_optimizer.py
python tests/test_custom_programs.py
```

Details: [tests/README.md](tests/README.md)

## Struktur

- `bot/handlers/` – Telegram-Schicht (ein Modul pro Funktion: profile, preferences, custom_program, points, goals, payment, shopping, deals, status, setup, help, start, menu, errors, access)
- `bot/deals/` – Rewards-Feed: `sources.py` (Feed-Registry), `feeds.py` (Fetch/Parse), `matcher.py` (Klassifikation + Keyword-Relevanz), `service.py` (DB-Orchestrierung), `digest.py` (täglicher Digest)
- `bot/shopping/` – Shopping Optimizer: `sources.py`, `fetcher.py` (defensiver Parser), `categories.py` (Freitext-Matching), `service.py` (Ranking/Caching)
- `bot/recommendation_engine.py` – reine Ranking-Logik für `/zahlen`, ohne DB-/Telegram-Abhängigkeit
- `bot/whitelist.py` – Autorisierung: `.env`-Admins + DB-gestützte Access-Requests
- `bot/queries.py` – gemeinsame DB-Zugriffs-Helfer (inkl. Katalog-/Custom-Programm-Verwaltung)
- `bot/db.py` – Schema + additive Migrationen (nie destruktiv)

## Funktionsumfang

`/start`, `/profil` (Hub: Karten, Programme inkl. eigener/Custom-Programme, Reisepräferenzen, Priorität, Flughäfen), `/status`, `/punkte`, `/ziele`, `/zahlen`, `/shopping` (Shopping-Optimizer: wo lohnt sich ein konkreter Einkauf), `/deals` (personalisierter Rewards-Feed + täglicher Digest), `/setup`, `/hilfe` – alle auch über das Hauptmenü erreichbar. Zugriff nur für freigegebene Nutzer (Admin-Bootstrap über `.env`, weitere per Anfrage/Freigabe im Chat).

## Dokumentation

- `docs/OVERNIGHT_REPORT.md` – Phase 4–6 (historisch)
- `docs/PHASE7_REPORT.md` – Master-QA, Rewards-Feed-Ausbau, Access-Request-System, Security-Review
- `docs/SHOPPING_OPTIMIZER.md` – Zweck, Quellen, Ranking, Einschränkungen des Shopping-Optimizers
- `docs/FUTURE_MONETIZATION.md` – Skizze für später, nicht implementiert
- `docs/BRANDING.md` – Branding-Richtung
