"""Consolidated offline regression suite for Phases 1-6. No network except
where explicitly noted, uses its own throwaway SQLite DB (never the real
data/bot.sqlite3). Run with:

    cd ~/Projects/travel-hacking-bot
    source .venv/bin/activate
    python tests/test_regression.py

Exits non-zero (via AssertionError) on the first failing check.
"""

import asyncio
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEST_DB = "/tmp/th_regression.sqlite3"
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

os.environ["BOT_TOKEN"] = "dummy:token"
os.environ["ALLOWED_USER_IDS"] = "42,99"
os.environ["DB_PATH"] = TEST_DB

from tests.helpers import Ctx, make_callback_update, make_message_update  # noqa: E402

passed = 0


def check(label: str, condition: bool):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"OK {label}")


# ---------------------------------------------------------------------------
# DB migration: idempotency + a simulated pre-Phase-2B database upgrades
# cleanly without losing data (see tests/test_db_migration.py for the fuller
# from-scratch-old-schema version; this just checks init_db() is safe to
# call repeatedly, which happens on every bot start).
# ---------------------------------------------------------------------------
from bot.db import get_connection, init_db  # noqa: E402

init_db()
init_db()  # must be idempotent - every bot start calls this
conn = get_connection()
program_count = conn.execute("SELECT COUNT(*) c FROM programs").fetchone()["c"]
conn.close()
check("init_db() is idempotent (safe to call twice, no duplicate programs)", program_count == 12)

from bot.deals.feeds import extract_items  # noqa: E402
from bot.handlers.deals import deals_entry  # noqa: E402
from bot.handlers.goals import ziel_activate, ziel_receive_amount, ziel_receive_label, ziel_receive_program, ziel_new_start  # noqa: E402
from bot.handlers.payment import zahlen_category  # noqa: E402
from bot.handlers.points import punkte_choose_program, punkte_entry, punkte_receive_value  # noqa: E402
from bot.handlers.preferences import edit_field_receive, edit_field_start, prefset_callback, show_prioritaet  # noqa: E402
from bot.handlers.profile import profil, profil_callback, profil_show_cards, profil_show_programs  # noqa: E402
from bot.handlers.start import start  # noqa: E402
from bot.handlers.status import status  # noqa: E402
from bot.queries import get_user_preferences  # noqa: E402
from bot.recommendation_engine import recommend as rec_engine_recommend  # noqa: E402
from bot.deals.matcher import rank_deals  # noqa: E402


async def run():
    conn = get_connection()
    prog = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM programs")}
    conn.close()

    # --- Phase 1/2A: /start + /profil (now a hub, Phase 5) ---
    ctx42, ctx99 = Ctx(), Ctx()
    u, _ = make_message_update(42, "/start")
    await start(u, ctx42)
    u, _ = make_message_update(99, "/start")
    await start(u, ctx99)

    u, message = make_message_update(42, "/profil")
    await profil(u, ctx42)
    check("/profil shows the hub", "Mein Profil" in message.reply_text.call_args.args[0])

    u, q, _ = make_callback_update(42, "profilhub:karten")
    await profil_show_cards(u, ctx42)
    for name in ["Payback American Express", "Revolut"]:
        u, q, _ = make_callback_update(42, f"toggle:{prog[name]}")
        await profil_callback(u, ctx42)
    u, q, _ = make_callback_update(42, "done")
    await profil_callback(u, ctx42)

    u, q, _ = make_callback_update(42, "profilhub:programme")
    await profil_show_programs(u, ctx42)
    for name in ["Payback", "Miles & More"]:
        u, q, _ = make_callback_update(42, f"toggle:{prog[name]}")
        await profil_callback(u, ctx42)
    u, q, _ = make_callback_update(42, "done")
    await profil_callback(u, ctx42)

    conn = get_connection()
    names42 = {
        r["name"] for r in conn.execute(
            "SELECT p.name FROM card_profile cp JOIN programs p ON p.id=cp.program_id WHERE cp.user_id=42"
        )
    }
    conn.close()
    check(
        "Karten- und Programme-Submenu ergänzen sich statt sich zu überschreiben",
        names42 == {"Payback American Express", "Revolut", "Payback", "Miles & More"},
    )

    # user 99: only Wise, for isolation checks below
    u, q, _ = make_callback_update(99, "profilhub:karten")
    await profil_show_cards(u, ctx99)
    u, q, _ = make_callback_update(99, f"toggle:{prog['Wise']}")
    await profil_callback(u, ctx99)
    u, q, _ = make_callback_update(99, "done")
    await profil_callback(u, ctx99)

    # --- Phase 2B: /punkte core logic (handler-level; the known live-Telegram
    # routing bug is NOT reproduced by direct calls - see docs/OVERNIGHT_REPORT.md) ---
    u, message = make_message_update(42, "/punkte")
    await punkte_entry(u, ctx42)
    u, q, _ = make_callback_update(42, f"punkte_prog:{prog['Payback']}")
    await punkte_choose_program(u, ctx42)
    u, message = make_message_update(42, "8.450")
    await punkte_receive_value(u, ctx42)
    conn = get_connection()
    balance = conn.execute(
        "SELECT balance FROM point_balances WHERE user_id=42 AND program_id=?", (prog["Payback"],)
    ).fetchone()
    conn.close()
    check("/punkte upserts a balance correctly", balance is not None and balance["balance"] == 8450)

    # --- Phase 2B: /ziele ---
    u, q, _ = make_callback_update(42, "ziel_new")
    await ziel_new_start(u, ctx42)
    u, message = make_message_update(42, "Business Class nach Dubai")
    await ziel_receive_label(u, ctx42)
    u, q, _ = make_callback_update(42, f"ziel_prog:{prog['Miles & More']}")
    await ziel_receive_program(u, ctx42)
    u, message = make_message_update(42, "40000")
    await ziel_receive_amount(u, ctx42)
    conn = get_connection()
    active_goal = conn.execute("SELECT label FROM goals WHERE user_id=42 AND is_active=1").fetchone()
    conn.close()
    check("erstes /ziele-Ziel wird automatisch aktiv", active_goal is not None and active_goal["label"] == "Business Class nach Dubai")

    # --- Phase 3: recommendation engine + /zahlen, only the user's own cards ---
    recs = rec_engine_recommend(
        user_cards=[{"id": 1, "name": "Trade Republic", "emoji": None}],
        rule_rows=[],
    )
    check("recommendation_engine gibt bei fehlender Regel [] zurück statt zu raten", recs == [])

    u, q, _ = make_callback_update(42, "pay:category:supermarkt")
    await zahlen_category(u, ctx42)
    text42 = q.edit_message_text.call_args.args[0]
    check("/zahlen empfiehlt nur Payback American Express (User42s eigene Karte)", "Payback American Express" in text42 and "Trade Republic" not in text42)

    u, q, _ = make_callback_update(99, "pay:category:supermarkt")
    await zahlen_category(u, ctx99)
    text99 = q.edit_message_text.call_args.args[0]
    check("User99 (nur Wise) bekommt nie Payback Amex empfohlen", "Payback American Express" not in text99)

    # --- Phase 4: deals matcher isolation + no invented matches ---
    ranked = rank_deals(
        [{"title": "PAYBACK zu Miles & More Transferbonus", "summary": "", "published_at": ""}],
        user_programs=["Wise"],
    )
    check("Deal-Matcher liefert 0 Treffer, wenn kein Programm-Keyword passt", ranked == [])

    u, message = make_message_update(42, "/deals")
    await deals_entry(u, ctx42)
    check("/deals liefert sauberen Leerfall ohne gespeicherte Deals", "keine passenden neuen Aktionen" in message.reply_text.call_args.args[0])

    # --- Phase 5: preferences save + isolation ---
    u, q, _ = make_callback_update(42, "profilhub:prioritaet")
    await show_prioritaet(u, ctx42)
    u, q, _ = make_callback_update(42, "prefset:priority:miles")
    await prefset_callback(u, ctx42)
    u, q, _ = make_callback_update(42, "prefedit:home_airport")
    await edit_field_start(u, ctx42)
    u, message = make_message_update(42, "fra")
    await edit_field_receive(u, ctx42)

    conn = get_connection()
    prefs42 = get_user_preferences(conn, 42)
    prefs99 = get_user_preferences(conn, 99)
    conn.close()
    check("Präferenzen von User42 korrekt gespeichert (FRA, uppercased)", prefs42["home_airport"] == "FRA")
    check("User99 hat keine Präferenzen von User42 (Isolation)", prefs99 is None or prefs99["home_airport"] is None)

    u, message = make_message_update(42, "/status")
    await status(u, ctx42)
    status_text = message.reply_text.call_args.args[0]
    check("/status zeigt personalisierte Präferenzen (Phase 5)", "FRA" in status_text)

    print(f"\nALL {passed} REGRESSION CHECKS PASSED")


asyncio.run(run())
os.remove(TEST_DB)
