"""Phase 7F: personal rewards feed - classification, personalized ranking
(programs + preference boost), dedup, and the daily digest (including the
critical "no new deals -> no message sent" rule). No network except one
already-parsed synthetic feed (offline); real Telegram sends are always
mocked. Throwaway DB only.

Run with: python tests/test_rewards_feed.py
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEST_DB = "/tmp/th_rewards_feed.sqlite3"
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

os.environ["BOT_TOKEN"] = "dummy:token"
os.environ["ALLOWED_USER_IDS"] = "42,99"
os.environ["DB_PATH"] = TEST_DB

passed = 0


def check(label, condition):
    global passed
    assert condition, f"FAILED: {label}"
    passed += 1
    print(f"OK {label}")


from bot.deals.matcher import classify_deal, rank_deals  # noqa: E402
from bot.db import get_connection, init_db  # noqa: E402

init_db()

# --- classify_deal: category/merchant/loyalty_program from keywords only ---
known_programs = [
    "Trade Republic", "Payback American Express", "Wise", "Revolut",
    "Payback", "Miles & More", "Membership Rewards", "Flying Blue", "Avios",
    "Marriott Bonvoy", "Hilton Honors",
]

tags = classify_deal("PAYBACK: EDEKA Punkteaktion bis Monatsende", "5-fach Punkte bei EDEKA", known_programs)
check("classify_deal erkennt Kategorie shopping", tags["category"] == "shopping")
check("classify_deal erkennt Merchant EDEKA", tags["merchant"] == "EDEKA")
check("classify_deal erkennt loyalty_program Payback", tags["loyalty_program"] == "Payback")

tags2 = classify_deal("Miles & More Transferbonus zu Partnerprogrammen", "", known_programs)
check("classify_deal erkennt Kategorie miles", tags2["category"] == "miles")

tags3 = classify_deal("Hilton Honors Doppelpunkte-Wochenende", "", known_programs)
check("classify_deal erkennt Kategorie hotels", tags3["category"] == "hotels")

tags4 = classify_deal("Ein ganz allgemeiner Reisebericht ohne Stichworte", "", known_programs)
check("classify_deal faellt auf 'travel' zurueck, wenn nichts passt", tags4["category"] == "travel")
check("classify_deal erfindet kein loyalty_program ohne Treffer", tags4["loyalty_program"] is None)

# --- rank_deals: preference signals only BOOST an already-qualifying deal ---
deal_program_only = {"title": "Payback Punkteaktion", "summary": "", "published_at": "2026-01-01"}
deal_no_program = {"title": "FRA Flughafen Lounge Tipps", "summary": "", "published_at": "2026-01-01"}

ranked_no_prefs = rank_deals([deal_program_only, deal_no_program], ["Payback"])
check("rank_deals: nur Programm-Match qualifiziert", len(ranked_no_prefs) == 1 and ranked_no_prefs[0]["title"] == "Payback Punkteaktion")

ranked_with_prefs = rank_deals(
    [deal_no_program], ["Payback"], preference_signals=[("Heimatflughafen FRA", "FRA")]
)
check(
    "rank_deals: Praeferenz-Signal allein qualifiziert NICHT (kein Programm-Match)",
    ranked_with_prefs == [],
)

boosted = {"title": "Payback Aktion in FRA Lounge", "summary": "", "published_at": "2026-01-01"}
plain = {"title": "Payback Aktion andernorts", "summary": "", "published_at": "2026-01-01"}
ranked_boost = rank_deals([plain, boosted], ["Payback"], preference_signals=[("Heimatflughafen FRA", "FRA")])
check(
    "rank_deals: Praeferenz-Signal boostet einen bereits qualifizierenden Deal nach oben",
    ranked_boost[0]["title"] == "Payback Aktion in FRA Lounge",
)

# --- service.refresh_all_sources: classification persisted, dedup enforced ---
import bot.deals.service as deals_service  # noqa: E402

FAKE_ITEMS = [
    {
        "source": "reisetopia", "external_id": "https://x/1",
        "title": "PAYBACK zu Miles & More: 25% Transferbonus", "url": "https://x/1",
        "summary": "Transferbonus-Aktion.", "published_at": "2026-01-01",
    },
    {
        "source": "travel-dealz", "external_id": "https://x/2",
        "title": "Hilton Honors Doppelpunkte", "url": "https://x/2",
        "summary": "", "published_at": "2026-01-02",
    },
]


def fake_fetch_source(source):
    return [i for i in FAKE_ITEMS if i["source"] == source.key]


with patch.object(deals_service, "fetch_source", side_effect=fake_fetch_source):
    inserted_1 = deals_service.refresh_all_sources()
    inserted_2 = deals_service.refresh_all_sources()

check("Deal-Refresh speichert neue Deals", inserted_1 == 2)
check("Deal-Refresh dedupliziert bei erneutem Abruf", inserted_2 == 0)

conn = get_connection()
row = conn.execute("SELECT category, loyalty_program, confidence FROM deals WHERE external_id='https://x/1'").fetchone()
conn.close()
check("Kategorie/loyalty_program/confidence werden bei Ingestion persistiert", row["category"] == "miles" and row["loyalty_program"] == "Miles & More" and row["confidence"] == "public_rss")

# --- daily digest: dedup + "no new deals -> no message" ---
from bot.deals.digest import send_daily_digest_for_user  # noqa: E402
from bot.handlers.profile import profil, profil_callback  # noqa: E402
from bot.handlers.start import start  # noqa: E402
from tests.helpers import Ctx, make_callback_update, make_message_update  # noqa: E402


async def run():
    conn = get_connection()
    prog = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM programs")}
    conn.close()

    ctx42 = Ctx()
    u, _ = make_message_update(42, "/start")
    await start(u, ctx42)
    u, _ = make_message_update(42, "/profil")
    await profil(u, ctx42)
    u, q, _ = make_callback_update(42, "profilhub:programme")
    from bot.handlers.profile import profil_show_programs
    await profil_show_programs(u, ctx42)
    for name in ["Payback", "Miles & More"]:
        u, q, _ = make_callback_update(42, f"toggle:{prog[name]}")
        await profil_callback(u, ctx42)
    u, q, _ = make_callback_update(42, "done")
    await profil_callback(u, ctx42)

    # user 99: no matching programs at all
    u, _ = make_message_update(99, "/start")
    await start(u, ctx42)

    fake_bot = AsyncMock()
    sent_42 = await send_daily_digest_for_user(fake_bot, 42)
    check("Digest wird gesendet, wenn neue relevante Deals existieren", sent_42 is True)
    check("Digest ruft send_message genau einmal fuer User42 auf", fake_bot.send_message.await_count == 1)

    fake_bot_99 = AsyncMock()
    sent_99 = await send_daily_digest_for_user(fake_bot_99, 99)
    check("Digest OHNE passende Deals sendet NICHTS (kein Spam)", sent_99 is False)
    check("Kein send_message-Aufruf fuer User99 ohne Match", fake_bot_99.send_message.await_count == 0)

    # second run: same deals already notified -> nothing new -> no second send
    fake_bot_again = AsyncMock()
    sent_again = await send_daily_digest_for_user(fake_bot_again, 42)
    check("Digest sendet dieselben Deals nicht ein zweites Mal (Dedup)", sent_again is False)
    check("Kein erneuter send_message-Aufruf beim zweiten Digest-Lauf", fake_bot_again.send_message.await_count == 0)

    print(f"\nALL {passed} REWARDS FEED CHECKS PASSED")


asyncio.run(run())
os.remove(TEST_DB)
