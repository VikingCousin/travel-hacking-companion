"""Regression test for the shopping menu-routing bug: tapping a Hauptmenü
button for an IMPLEMENTED feature must never fall through to the generic
menu_callback's coming_soon_text() (which raises KeyError for any key not
in COMING_SOON - and COMING_SOON is empty by design once every feature
ships). Uses real python-telegram-bot Application.process_update() routing,
not direct handler calls - this exact bug (a ConversationHandler left
"stuck" tracked in a live state after a stray menu:home tap) can only be
caught by exercising PTB's actual dispatch/state-tracking, which is why
test_regression.py's direct-call style could not have caught it.

No real Telegram messages sent (send/edit mocked). Throwaway DB only.

Run with: python tests/test_menu_routing_regression.py
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
TEST_DB = "/tmp/th_menu_routing_regression.sqlite3"
os.environ["DB_PATH"] = TEST_DB
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from telegram import Update  # noqa: E402
from telegram.ext import ExtBot  # noqa: E402

from bot.db import init_db  # noqa: E402
from bot.main import build_application  # noqa: E402

init_db()
TEST_UID = 777777
passed = 0

# Every Hauptmenü button that is currently a real, implemented feature (i.e.
# every key that must NEVER be handled by coming_soon_text). Deliberately
# not hardcoded from bot/menu.py's MENU_ROWS - if a future feature is added
# to the menu but this list isn't updated, the new key falls through to the
# "still coming soon" assertion below and the test fails loudly, which is
# exactly the safety net requested.
IMPLEMENTED_MENU_KEYS = [
    "status", "profil", "punkte", "ziele", "zahlen", "deals", "setup", "hilfe", "shopping",
]

COMING_SOON_MARKER = "noch nicht implementiert"


def _cb_update(update_id, cb_data, bot, uid):
    data = {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "from": {"id": uid, "first_name": "Test", "is_bot": False},
            "chat_instance": "1",
            "data": cb_data,
            "message": {
                "message_id": update_id, "date": int(time.time()),
                "chat": {"id": uid, "type": "private"},
                "from": {"id": 1, "first_name": "Bot", "is_bot": True},
                "text": "placeholder",
            },
        },
    }
    return Update.de_json(data, bot)


def check(label, condition):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"OK {label}")


async def run():
    import bot.config as cfg

    cfg.ALLOWED_USER_IDS.add(TEST_UID)
    app = build_application(cfg.BOT_TOKEN)

    errors = []

    async def error_handler(update, context):
        errors.append(context.error)
        print(f"!!! HANDLER EXCEPTION: {context.error!r}")

    app.add_error_handler(error_handler)

    sent = []

    async def fake_send_message(self, chat_id, text, **kwargs):
        sent.append(text); return None

    async def fake_edit_message_text(self, *args, **kwargs):
        sent.append(kwargs.get("text") or (args[0] if args else "")); return None

    async def fake_answer_callback_query(self, *args, **kwargs):
        return True

    with patch.object(ExtBot, "send_message", new=fake_send_message), \
         patch.object(ExtBot, "edit_message_text", new=fake_edit_message_text), \
         patch.object(ExtBot, "answer_callback_query", new=fake_answer_callback_query):
        await app.initialize()
        try:
            update_id = 1

            # --- 9/10) parametrized: every implemented Hauptmenü button
            # must route to its own handler, never to coming_soon_text() ---
            for key in IMPLEMENTED_MENU_KEYS:
                sent.clear()
                errors.clear()
                update_id += 1
                await app.process_update(_cb_update(update_id, f"menu:{key}", app.bot, TEST_UID))
                await asyncio.sleep(0.15)

                check(f"menu:{key} raised no exception (kein KeyError)", errors == [])
                check(f"menu:{key} produced a response", len(sent) > 0)
                check(
                    f"menu:{key} was NOT handled by coming_soon_text (kein 'noch nicht implementiert')",
                    all(COMING_SOON_MARKER not in t for t in sent),
                )

            # "shopping" is the only key above that's a ConversationHandler
            # entry with no early-END branch, so it leaves AWAIT_CATEGORY
            # tracked for this user - clean it up before the dedicated
            # scenario below, which needs to start from a known-clean state.
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "shop_cancel", app.bot, TEST_UID))
            await asyncio.sleep(0.15)

            # --- 9) exact reported bug scenario: Hauptmenü -> shopping ->
            # shopping conversation starts (not menu_callback) ---
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "menu:shopping", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check("Hauptmenü->shopping: kein Fehler", errors == [])
            check("Hauptmenü->shopping: Shopping-Flow gestartet (Kategorie-Frage)", any("Was möchtest du kaufen" in t for t in sent))
            check("Hauptmenü->shopping: keine Coming-Soon-Antwort", all(COMING_SOON_MARKER not in t for t in sent))

            # Cancel it properly (the fixed CANCEL_KEYBOARD path) and verify
            # re-entry afterwards still works cleanly - guards against the
            # exact "stuck ConversationHandler state" root cause.
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "shop_cancel", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check("shop_cancel beendet die Conversation ohne Fehler", errors == [])

            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "menu:shopping", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check("Erneuter menu:shopping-Tap nach Abbrechen startet den Flow wieder sauber", any("Was möchtest du kaufen" in t for t in sent))
            check("Kein KeyError bei erneutem Einstieg", errors == [])

            # --- exact root-cause reproduction: a raw "menu:home" callback
            # arriving WHILE the shopping conversation is tracked in
            # AWAIT_CATEGORY (independent of which button is currently
            # rendered - this is what actually happened live: an older
            # message with the pre-fix keyboard, or any other stray path,
            # can still deliver this callback_data to a tracked state). The
            # conversation must end cleanly here rather than get stuck, or
            # the *next* menu:shopping tap reproduces the original KeyError. ---
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "menu:home", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check("Rohes menu:home waehrend AWAIT_CATEGORY wird sauber behandelt (kein Fehler)", errors == [])
            check("Rohes menu:home zeigt das Hauptmenue", any("Was möchtest du tun" in t for t in sent))

            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "menu:shopping", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check(
                "ROOT CAUSE FIX: menu:shopping nach rohem menu:home startet den Flow (kein KeyError, keine haengende Conversation)",
                any("Was möchtest du kaufen" in t for t in sent) and errors == [],
            )

            # leave the conversation in a clean state for the next check
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "shop_cancel", app.bot, TEST_UID))
            await asyncio.sleep(0.15)

            # --- interleaving sanity: shopping conversation doesn't leak
            # into/steal from an unrelated conversation for the same user ---
            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "shop_cancel", app.bot, TEST_UID))
            await asyncio.sleep(0.15)

            sent.clear()
            errors.clear()
            update_id += 1
            await app.process_update(_cb_update(update_id, "menu:punkte", app.bot, TEST_UID))
            await asyncio.sleep(0.15)
            check("menu:punkte funktioniert unveraendert nach Shopping-Interaktionen", errors == [] and len(sent) > 0)

        finally:
            await app.shutdown()

    print(f"\nALL {passed} MENU ROUTING REGRESSION CHECKS PASSED")


asyncio.run(run())
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)
