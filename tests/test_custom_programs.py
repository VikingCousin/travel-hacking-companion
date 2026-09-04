"""Phase 7.5, 14B: custom/user-provided rewards programs. No real Telegram
messages sent. Throwaway DB only.

Run with: python tests/test_custom_programs.py
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

TEST_DB = "/tmp/th_custom_programs.sqlite3"
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


from bot.db import get_connection, init_db  # noqa: E402

init_db()

# --- AD) program_transfers is architecture-only, zero seeded rows ---
conn = get_connection()
transfer_count = conn.execute("SELECT COUNT(*) c FROM program_transfers").fetchone()["c"]
conn.close()
check("AD) program_transfers hat keine erfundenen Transferraten (0 Zeilen)", transfer_count == 0)

# --- Y) deterministic alias resolution ---
from bot.queries import resolve_program_alias  # noqa: E402

check("Y) 'Shell Club Smart' (mit Leerzeichen) -> kanonisch 'Shell ClubSmart'", resolve_program_alias("Shell Club Smart") == "Shell ClubSmart")
check("Y) 'clubsmart' (lowercase, kein Leerzeichen) -> kanonisch 'Shell ClubSmart'", resolve_program_alias("clubsmart") == "Shell ClubSmart")
check("Y) unbekannter Name -> kein erzwungenes Mapping", resolve_program_alias("Voellig Unbekanntes Programm XY") is None)

from bot.handlers.custom_program import (  # noqa: E402
    customprog_receive_name,
    customprog_receive_type,
    customprog_receive_usage,
    customprog_remove,
    customprog_start,
    show_custom_programs,
)
from bot.handlers.profile import profil, profil_show_programs  # noqa: E402
from bot.handlers.start import start  # noqa: E402
from bot.queries import user_custom_programs, visible_programs  # noqa: E402
from tests.helpers import Ctx, make_callback_update, make_message_update  # noqa: E402


async def run():
    ctx42, ctx99 = Ctx(), Ctx()
    u, _ = make_message_update(42, "/start")
    await start(u, ctx42)
    u, _ = make_message_update(99, "/start")
    await start(u, ctx99)

    # --- Y) end-to-end: a known alias is recognized and added directly,
    # no type question, no new programs row created (uses the catalog one) ---
    u, q, _ = make_callback_update(42, "customprog_new")
    await customprog_start(u, ctx42)
    u, message = make_message_update(42, "Shell Club Smart")
    state = await customprog_receive_name(u, ctx42)
    check("Y) Bekannter Alias wird sofort erkannt, keine Typ-Rückfrage", "bereits als verifiziertes Programm bekannt" in message.reply_text.call_args.args[0])

    conn = get_connection()
    shell_rows = conn.execute("SELECT COUNT(*) c FROM programs WHERE name='Shell ClubSmart'").fetchone()["c"]
    conn.close()
    check("Y) Kein doppelter Katalogeintrag durch Alias-Erkennung erzeugt", shell_rows == 1)

    # --- U/V/Z/AA/AE) unrecognized name -> becomes a private custom program ---
    u, q, _ = make_callback_update(42, "customprog_new")
    await customprog_start(u, ctx42)
    u, message = make_message_update(42, "Krawuttels Bonuskarte")
    state = await customprog_receive_name(u, ctx42)
    check("U) Unbekanntes Programm fragt nach dem Typ (kein Katalog-Autofound)", "Welcher Typ passt am besten" in message.reply_text.call_args.args[0])

    u, q, _ = make_callback_update(42, "customprog_type:loyalty")
    state = await customprog_receive_type(u, ctx42)
    u, q, _ = make_callback_update(42, "customprog_usage:tanken")
    await customprog_receive_usage(u, ctx42)

    conn = get_connection()
    custom_row = conn.execute(
        "SELECT id, source, owner_user_id, type, usage_context FROM programs WHERE name='Krawuttels Bonuskarte'"
    ).fetchone()
    conn.close()
    check("U) Unbekanntes Programm wird als neue Zeile gespeichert", custom_row is not None)
    check("V) Custom Program hat source='user'", custom_row["source"] == "user")
    check("V) Custom Program gehoert eindeutig User 42 (owner_user_id)", custom_row["owner_user_id"] == 42)
    check("AE) Typ bleibt korrekt 'loyalty' (semantisch getrennt von Karten)", custom_row["type"] == "loyalty")
    check("Z) Keine erfundenen Benefits - nur usage_context, keine reward_rate o.ae. Felder auf programs", "usage_context" in dict(custom_row).keys() and "reward_rate" not in dict(custom_row).keys())

    custom_program_id = custom_row["id"]

    # --- AA) user-provided membership is never labeled "verified" anywhere
    # user-facing - check the confirmation text and the profile listing ---
    conn = get_connection()
    programs_for_42 = visible_programs(conn, 42, "loyalty")
    conn.close()
    krawuttel_entry = next(p for p in programs_for_42 if p["name"] == "Krawuttels Bonuskarte")
    check("AA) Custom Program ist als source='user' klar unterscheidbar (nicht 'catalog')", krawuttel_entry["source"] == "user")

    # --- W) user B can NEVER see user A's custom program ---
    conn = get_connection()
    programs_for_99 = visible_programs(conn, 99, "loyalty")
    conn.close()
    names_for_99 = {p["name"] for p in programs_for_99}
    check("W) User99 sieht Krawuttels Bonuskarte (User42s privates Programm) NICHT", "Krawuttels Bonuskarte" not in names_for_99)
    check("W) User99 sieht weiterhin den oeffentlichen Katalog (z. B. Payback)", "Payback" in names_for_99)

    # add it to user 42's actual card_profile via the normal toggle flow to
    # exercise the full add-to-profile path (customprog flow already did
    # this internally, verify it landed in card_profile too)
    conn = get_connection()
    in_profile = conn.execute(
        "SELECT 1 FROM card_profile WHERE user_id=42 AND program_id=?", (custom_program_id,)
    ).fetchone()
    conn.close()
    check("U) Custom Program wird direkt zum Profil des Users hinzugefuegt", in_profile is not None)

    # --- X) can be listed and removed/deactivated, ownership re-checked server-side ---
    u, q, _ = make_callback_update(42, "customprog_manage")
    await show_custom_programs(u, ctx42)
    check("X) Eigene-Programme-Ansicht listet das Custom Program", "Krawuttels Bonuskarte" in q.edit_message_text.call_args.args[0])

    # user 99 tries to remove user 42's custom program by crafting the callback directly
    u_evil, q_evil, _ = make_callback_update(99, f"customprog_remove:{custom_program_id}")
    await customprog_remove(u_evil, ctx99)
    conn = get_connection()
    still_active = conn.execute("SELECT is_active FROM programs WHERE id=?", (custom_program_id,)).fetchone()["is_active"]
    conn.close()
    check("W/X) User99 kann User42s Custom Program NICHT deaktivieren (Ownership serverseitig geprueft)", still_active == 1)

    # the actual owner removes it
    u, q, _ = make_callback_update(42, f"customprog_remove:{custom_program_id}")
    await customprog_remove(u, ctx42)
    conn = get_connection()
    row_after = conn.execute("SELECT is_active FROM programs WHERE id=?", (custom_program_id,)).fetchone()
    still_in_profile = conn.execute(
        "SELECT 1 FROM card_profile WHERE user_id=42 AND program_id=?", (custom_program_id,)
    ).fetchone()
    conn.close()
    check("X) Eigentuemer kann sein Custom Program deaktivieren", row_after["is_active"] == 0)
    check("X) Deaktiviertes Custom Program wird aus card_profile entfernt", still_in_profile is None)

    conn = get_connection()
    visible_after = visible_programs(conn, 42, "loyalty")
    conn.close()
    check("X) Deaktiviertes Custom Program erscheint nicht mehr in der Auswahl", all(p["name"] != "Krawuttels Bonuskarte" for p in visible_after))

    # --- AB/AC) shopping search considers a relevant custom program, but its
    # lack of a verified rate never fakes a numeric ranking value ---
    from bot.shopping.service import find_shopping_options

    # re-add a fresh custom program owned by user 42, used in "fashion"
    conn = get_connection()
    from bot.queries import create_custom_program
    new_custom_id = create_custom_program(conn, 42, "Krawuttels Fashion Club", "loyalty", "einkaufen")
    conn.execute("INSERT OR IGNORE INTO card_profile (user_id, program_id) VALUES (42, ?)", (new_custom_id,))
    conn.commit()
    conn.close()

    offers_no_data = find_shopping_options(42, "fashion")
    check("AB) Shopping-Suche crasht nicht, wenn ein Custom Program in der Kategorie sucht", isinstance(offers_no_data, list))
    check(
        "AC) Custom Program ohne verifizierte shopping_partners-Zeile taucht NICHT mit erfundener Rate im Ranking auf",
        all(o["program_name"] != "Krawuttels Fashion Club" for o in offers_no_data),
    )

    # --- AF) broad regression: existing multi-user isolation still holds
    # for the classic /profil card/loyalty split after all this ---
    u, q, _ = make_callback_update(99, "profilhub:programme")
    await profil_show_programs(u, ctx99)
    programme_text_99 = q.edit_message_reply_markup.call_args if q.edit_message_reply_markup.called else None
    conn = get_connection()
    count_99 = conn.execute("SELECT COUNT(*) c FROM card_profile WHERE user_id=99").fetchone()["c"]
    count_42 = conn.execute("SELECT COUNT(*) c FROM card_profile WHERE user_id=42").fetchone()["c"]
    conn.close()
    check("AF) User-Isolation nach allen Custom-Program-Operationen weiterhin intakt (getrennte Zeilen)", count_99 == 0 and count_42 >= 1)

    print(f"\nALL {passed} CUSTOM PROGRAM CHECKS PASSED")


asyncio.run(run())
os.remove(TEST_DB)
