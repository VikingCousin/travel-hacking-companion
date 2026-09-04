"""Phase 7I/7L: access-request system and security checks. No real Telegram
messages ever sent - context.bot.send_message is always mocked. Throwaway DB
only.

Run with: python tests/test_access_and_security.py
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEST_DB = "/tmp/th_access_security.sqlite3"
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

ADMIN_ID = 42
NON_ADMIN_ID = 999
REQUESTER_ID = 12345

os.environ["BOT_TOKEN"] = "dummy:token"
os.environ["ALLOWED_USER_IDS"] = str(ADMIN_ID)
os.environ["DB_PATH"] = TEST_DB

passed = 0


def check(label, condition):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"OK {label}")


from bot.db import get_connection, init_db  # noqa: E402

init_db()

from bot.handlers.access import decide_access, request_access  # noqa: E402
from bot.whitelist import is_authorized, restricted  # noqa: E402
from tests.helpers import Ctx, make_callback_update, make_message_update  # noqa: E402


async def run():
    ctx = Ctx()

    check("Unbekannter Nutzer ist initial NICHT autorisiert", is_authorized(REQUESTER_ID) is False)
    check("Admin (ALLOWED_USER_IDS) ist immer autorisiert", is_authorized(ADMIN_ID) is True)

    # @restricted on a denied user shows the request button, not a bare denial
    @restricted
    async def dummy_handler(update, context):
        raise AssertionError("should never be called for an unauthorized user")

    u, message = make_message_update(REQUESTER_ID, "/start")
    await dummy_handler(u, ctx)
    denial_markup = message.reply_text.call_args.kwargs["reply_markup"]
    denial_buttons = [b.text for row in denial_markup.inline_keyboard for b in row]
    check("@restricted zeigt 'Zugang anfragen'-Button bei fehlender Autorisierung", any("Zugang anfragen" in t for t in denial_buttons))

    # requester taps "Zugang anfragen" -> pending row + admin gets notified
    u, q, _ = make_callback_update(REQUESTER_ID, "access:request")
    u.effective_user.username = "testrequester"
    fake_context = MagicMock()
    fake_context.bot = AsyncMock()
    await request_access(u, fake_context)

    conn = get_connection()
    row = conn.execute("SELECT status FROM access_requests WHERE telegram_id=?", (REQUESTER_ID,)).fetchone()
    conn.close()
    check("Zugangsanfrage wird als 'pending' gespeichert", row["status"] == "pending")
    check("Admin wird per send_message benachrichtigt", fake_context.bot.send_message.await_count == 1)
    notify_kwargs = fake_context.bot.send_message.call_args.kwargs
    check("Admin-Benachrichtigung geht an die richtige chat_id", notify_kwargs["chat_id"] == ADMIN_ID)
    check("Keine numerische User-ID im sichtbaren Button-Text", all(str(REQUESTER_ID) not in t for t in ["✅ Freigeben", "❌ Ablehnen"]))

    # a non-admin must NEVER be able to approve, even with a crafted callback
    u2, q2, _ = make_callback_update(NON_ADMIN_ID, f"access:approve:{REQUESTER_ID}")
    fake_context2 = MagicMock()
    fake_context2.bot = AsyncMock()
    await decide_access(u2, fake_context2)
    conn = get_connection()
    row_after_fake = conn.execute("SELECT status FROM access_requests WHERE telegram_id=?", (REQUESTER_ID,)).fetchone()
    conn.close()
    check("Nicht-Admin kann NICHT freigeben (serverseitig geprueft)", row_after_fake["status"] == "pending")
    q2.answer.assert_awaited()
    check("Nicht-Admin bekommt einen Alert statt einer stillen Ausfuehrung", q2.answer.call_args.kwargs.get("show_alert") is True)

    # self-approval defense: even if a requester somehow crafted this callback
    u3, q3, _ = make_callback_update(REQUESTER_ID, f"access:approve:{REQUESTER_ID}")
    fake_context3 = MagicMock()
    fake_context3.bot = AsyncMock()
    await decide_access(u3, fake_context3)
    conn = get_connection()
    row_self = conn.execute("SELECT status FROM access_requests WHERE telegram_id=?", (REQUESTER_ID,)).fetchone()
    conn.close()
    check("Self-Approval ist ausgeschlossen (Requester ist nie Admin)", row_self["status"] == "pending")

    # real admin approves
    u4, q4, _ = make_callback_update(ADMIN_ID, f"access:approve:{REQUESTER_ID}")
    fake_context4 = MagicMock()
    fake_context4.bot = AsyncMock()
    await decide_access(u4, fake_context4)
    conn = get_connection()
    row_approved = conn.execute("SELECT status, decided_by FROM access_requests WHERE telegram_id=?", (REQUESTER_ID,)).fetchone()
    conn.close()
    check("Admin kann freigeben", row_approved["status"] == "approved")
    check("decided_by wird korrekt gesetzt", row_approved["decided_by"] == ADMIN_ID)
    check("Requester wird nach Freigabe direkt autorisiert", is_authorized(REQUESTER_ID) is True)
    check("Requester wird ueber die Freigabe benachrichtigt", fake_context4.bot.send_message.await_count == 1)

    # second requester gets rejected
    REJECTED_ID = 54321
    u5, q5, _ = make_callback_update(REJECTED_ID, "access:request")
    u5.effective_user.username = None
    u5.effective_user.first_name = "Test<b>Injection</b>_"
    fake_context5 = MagicMock()
    fake_context5.bot = AsyncMock()
    await request_access(u5, fake_context5)

    u6, q6, _ = make_callback_update(ADMIN_ID, f"access:reject:{REJECTED_ID}")
    fake_context6 = MagicMock()
    fake_context6.bot = AsyncMock()
    await decide_access(u6, fake_context6)
    check("Abgelehnter Nutzer bleibt unautorisiert", is_authorized(REJECTED_ID) is False)

    print(f"\nAccess-request checks passed so far: {passed}")


asyncio.run(run())


# ---------------------------------------------------------------------------
# 7B / 7L: harmless "message is not modified" is swallowed, real errors aren't
# ---------------------------------------------------------------------------
import time  # noqa: E402

from telegram import Update  # noqa: E402
from telegram.error import BadRequest  # noqa: E402

from bot.handlers.errors import handle_error  # noqa: E402


def _real_update(update_id, uid):
    """A genuine telegram.Update (not a MagicMock) - errors.py's isinstance()
    guard means it needs the real type to exercise the actual code path."""
    data = {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(time.time()),
            "chat": {"id": uid, "type": "private"},
            "from": {"id": uid, "first_name": "Test", "is_bot": False},
            "text": "irrelevant",
        },
    }
    return Update.de_json(data, bot=None)


class FakeContext:
    def __init__(self, error):
        self.error = error
        self.bot = AsyncMock()


async def run_error_checks():
    global passed

    ctx = FakeContext(BadRequest("Message is not modified: specified new message content..."))
    await handle_error(_real_update(1, 1), ctx)
    check("'message is not modified' wird still verschluckt, kein Fehlertext an den Nutzer", ctx.bot.send_message.await_count == 0)

    ctx2 = FakeContext(ValueError("something genuinely broke"))
    await handle_error(_real_update(2, 1), ctx2)
    check("Ein echter Fehler zeigt weiterhin die freundliche Nutzer-Meldung", ctx2.bot.send_message.await_count == 1)
    check("Freundliche Meldung enthaelt keinen Traceback/Technik-Jargon", "Traceback" not in ctx2.bot.send_message.call_args.kwargs["text"])


asyncio.run(run_error_checks())


# ---------------------------------------------------------------------------
# 7L: no secrets in source (grep-style check on the actual files, not just
# runtime logs - catches an accidentally hardcoded token just as well)
# ---------------------------------------------------------------------------
import re  # noqa: E402

BOT_TOKEN_PATTERN = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")
for root, _, files in os.walk(os.path.join(PROJECT_ROOT, "bot")):
    for fname in files:
        if not fname.endswith(".py"):
            continue
        path = os.path.join(root, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert not BOT_TOKEN_PATTERN.search(content), f"FAILED: possible hardcoded bot token in {path}"
passed += 1
print("OK kein hartkodierter Bot-Token in bot/*.py gefunden")

env_path = os.path.join(PROJECT_ROOT, ".gitignore")
with open(env_path, encoding="utf-8") as f:
    gitignore = f.read()
check(".env ist in .gitignore gelistet", ".env" in gitignore)


# ---------------------------------------------------------------------------
# JobQueue registration: deal refresh + daily digest are both scheduled
# ---------------------------------------------------------------------------
from bot.main import build_application  # noqa: E402
import bot.config as cfg  # noqa: E402

app = build_application(cfg.BOT_TOKEN)
job_names = {job.name for job in app.job_queue.jobs()} if app.job_queue else set()
check("JobQueue: Deal-Refresh-Job registriert", "_refresh_deals_job" in job_names)
check("JobQueue: Daily-Digest-Job registriert", "send_daily_digest_job" in job_names)

os.remove(TEST_DB)
print(f"\nALL {passed} ACCESS/SECURITY CHECKS PASSED")
