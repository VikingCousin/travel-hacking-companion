# Tests

No pytest dependency - plain scripts, each runnable directly and exiting
non-zero on the first failed `assert`. All of them use a throwaway SQLite
file under `/tmp/`, never `data/bot.sqlite3`. Every real Telegram send/edit
call is mocked in every file - nothing here ever messages a real chat.

```bash
cd ~/Projects/travel-hacking-bot
source .venv/bin/activate
python tests/test_regression.py          # handler-level checks across all phases
python tests/test_db_migration.py        # schema/constraints after init_db()
python tests/test_routing.py             # real PTB Application.process_update() routing
python tests/test_rewards_feed.py        # deal classification, personalized ranking, digest dedup
python tests/test_access_and_security.py # access-request flow, admin-only, error handler, secrets scan
python tests/test_shopping_optimizer.py  # category matching, ranking, unit-safety, fetcher resilience
python tests/test_custom_programs.py     # user-owned programs, catalog isolation, alias recognition
python tests/test_menu_routing_regression.py  # every Hauptmenü button + the shopping stuck-conversation bug
```

`test_routing.py`, `test_shopping_optimizer.py`, and
`test_menu_routing_regression.py` need a valid `BOT_TOKEN` in `.env` (each
makes one legitimate, read-only `getMe()` call to initialize the Bot
object). `test_shopping_optimizer.py` also makes one live,
respectful request to the real `payback.de` shopping page and to a
deliberately-nonexistent domain (to verify a broken source never crashes
the fetcher) - everything else is offline.

`test_routing.py` is the one that matters most for catching handler
registration/order bugs: `test_regression.py` calls handler functions
directly and so can't detect a routing/order problem, only real
`Application.process_update()` dispatch can. The originally-known live
`/punkte` issue was never reproducible in either style of test - see
`docs/PHASE7_REPORT.md`.
