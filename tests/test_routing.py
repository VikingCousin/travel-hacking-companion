"""Real python-telegram-bot Application routing smoke test: builds the exact
handler registration from bot/main.py and feeds it synthetic Updates through
Application.process_update() - the actual dispatch path run_polling() uses -
instead of calling handler functions directly. This is the only kind of test
that would have caught the known /punkte registration-order class of bug (see
docs/OVERNIGHT_REPORT.md); handler-level tests in test_regression.py cannot.

Uses the project's real BOT_TOKEN from .env for one legitimate, read-only
getMe() call (required to initialize the Bot object) - every send/edit call
is mocked, so nothing is ever actually sent to Telegram. DB_PATH is
redirected to a throwaway file, never the real data/bot.sqlite3.

Run with:
    python tests/test_routing.py
"""

import asyncio
import logging
import os
import sys
import time
from unittest.mock import patch

logging.basicConfig(level=logging.WARNING)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
TEST_DB = "/tmp/th_routing_check.sqlite3"
os.environ["DB_PATH"] = TEST_DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from telegram import Update  # noqa: E402
from telegram.ext import ExtBot  # noqa: E402

from bot.db import init_db  # noqa: E402
from bot.main import build_application  # noqa: E402

init_db()
TEST_UID = 555555
passed = 0


def make_msg_update(update_id, text, bot, uid):
    entities = []
    if text.startswith("/"):
        entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    data = {
        "update_id": update_id,
        "message": {
            "message_id": update_id, "date": int(time.time()),
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "first_name": "Test", "is_bot": False},
            "text": text, "entities": entities,
        },
    }
    return Update.de_json(data, bot)


def make_cb_update(update_id, cb_data, bot, uid):
    data = {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "from": {"id": uid, "first_name": "Test", "is_bot": False},
            "chat_instance": "1", "data": cb_data,
            "message": {
                "message_id": update_id, "date": int(time.time()),
                "chat": {"id": uid, "type": "private"},
                "from": {"id": 1, "first_name": "Bot", "is_bot": True},
                "text": "placeholder",
            },
        },
    }
    return Update.de_json(data, bot)


async def error_handler(update, context):
    print(f"!!! HANDLER EXCEPTION for update {update}: {context.error!r}")


async def run():
    import bot.config as cfg

    cfg.ALLOWED_USER_IDS.add(TEST_UID)

    app = build_application(cfg.BOT_TOKEN)
    app.add_error_handler(error_handler)

    sent = []

    async def fake_send_message(self, chat_id, text, **kwargs):
        sent.append(text)
        return None

    async def fake_edit_message_text(self, *args, **kwargs):
        sent.append(kwargs.get("text") or (args[0] if args else ""))
        return None

    async def fake_answer_callback_query(self, *args, **kwargs):
        return True

    global passed

    with patch.object(ExtBot, "send_message", new=fake_send_message), \
         patch.object(ExtBot, "edit_message_text", new=fake_edit_message_text), \
         patch.object(ExtBot, "answer_callback_query", new=fake_answer_callback_query):
        await app.initialize()
        print(f"Bot initialized as @{app.bot.username}")

        try:
            checks = [
                ("/start", "msg", "Travel Hacking Companion"),
                ("/profil", "msg", "Mein Profil"),
                ("/status", "msg", "Dein Status"),
                ("/zahlen", "msg", "Womit möchtest du zahlen"),
                ("/deals", "msg", "Für dich"),
                ("/setup", "msg", "Einrichtung"),
                ("/hilfe", "msg", "Funktionen"),
                ("/ziele", "msg", "Deine Ziele"),
                ("/punkte", "msg", "Loyalty-Programme"),  # Phase 7: no longer reproducible, see docs/PHASE7_REPORT.md
                ("menu:status", "cb", "Dein Status"),
                ("menu:profil", "cb", "Mein Profil"),
                ("menu:zahlen", "cb", "Womit möchtest du zahlen"),
                ("menu:deals", "cb", "Für dich"),
                ("menu:hilfe", "cb", "Funktionen"),
                ("menu:setup", "cb", "Einrichtung"),
                ("menu:home", "cb", "Was möchtest du tun"),
                ("profilhub:karten", "cb", None),
                ("profilhub:programme", "cb", None),
                ("profilhub:reise", "cb", "Reisepräferenzen"),
                ("profilhub:prioritaet", "cb", "Priorität"),
                ("profilhub:flughaefen", "cb", "Flughäfen"),
            ]

            for i, (cmd_or_cb, kind, expect) in enumerate(checks, start=1):
                sent.clear()
                if kind == "msg":
                    update = make_msg_update(i, cmd_or_cb, app.bot, TEST_UID)
                else:
                    update = make_cb_update(i, cmd_or_cb, app.bot, TEST_UID)
                await app.process_update(update)
                await asyncio.sleep(0.15)

                if expect is None:
                    print(f"INFO {cmd_or_cb}: {len(sent)} message(s) - {sent}")
                    continue
                ok = any(expect in t for t in sent)
                status_label = "OK" if ok else "!!! FAIL"
                print(f"{status_label} {cmd_or_cb} -> expected {expect!r}: got {sent}")
                assert ok, f"routing check failed for {cmd_or_cb}: expected {expect!r} in {sent}"
                passed += 1

        finally:
            await app.shutdown()

    print(f"\nALL {passed} ROUTING CHECKS PASSED")


asyncio.run(run())
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
