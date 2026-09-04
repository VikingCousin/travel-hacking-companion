import asyncio
import datetime
import logging
from zoneinfo import ZoneInfo

from telegram import BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot.config import BOT_TOKEN
from bot.db import init_db
from bot.handlers.goals import (
    ziel_activate,
    ziel_delete_cancel,
    ziel_delete_confirm,
    ziel_delete_prompt,
    ziel_new_conversation,
    ziele_view,
)
from bot.deals.digest import send_daily_digest_job
from bot.deals.service import refresh_all_sources
from bot.handlers.access import decide_access, request_access
from bot.handlers.custom_program import (
    custom_program_conversation,
    customprog_remove,
    show_custom_programs,
)
from bot.handlers.deals import deals_entry, deals_more, deals_refresh
from bot.handlers.errors import handle_error
from bot.handlers.help import hilfe
from bot.handlers.menu import menu_callback
from bot.handlers.payment import zahlen_category, zahlen_entry, zahlen_restart, zahlen_subcategory
from bot.handlers.points import punkte_conversation
from bot.handlers.preferences import (
    pref_edit_conversation,
    prefpick_start,
    prefset_callback,
    show_flughaefen,
    show_prioritaet,
    show_reise,
)
from bot.handlers.profile import profil, profil_callback, profil_show_cards, profil_show_programs
from bot.handlers.setup import setup
from bot.handlers.shopping import shopping_conversation, shopping_to_karte
from bot.handlers.start import start
from bot.handlers.status import status
from bot.shopping.service import refresh_shopping_partners

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# httpx logs every request URL at INFO level, which includes the bot token
# (https://api.telegram.org/bot<TOKEN>/...). Raise it to WARNING so the token
# never reaches the terminal, while our own logs stay at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_COMMANDS = [
    BotCommand("start", "Bot starten & Hauptmenü"),
    BotCommand("profil", "Karten & Programme verwalten"),
    BotCommand("status", "Dein Dashboard: Punkte & Ziel-Fortschritt"),
    BotCommand("punkte", "Punktestand eintragen/aktualisieren"),
    BotCommand("ziele", "Ziele anlegen, aktivieren, löschen"),
    BotCommand("zahlen", "Womit zahle ich bei X?"),
    BotCommand("shopping", "Einkauf optimieren: wo lohnt sich der Kauf?"),
    BotCommand("deals", "Relevante Travel-Deals für dein Profil"),
    BotCommand("setup", "Einrichtung erklärt"),
    BotCommand("hilfe", "Alle Funktionen erklärt"),
]

# Wie oft die drei öffentlichen Deal-Feeds automatisch neu abgerufen werden.
# Konservativ gehalten (kein Minutentakt) - reine Datenaktualisierung, sendet
# an niemanden eine Nachricht.
DEAL_REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
DEAL_REFRESH_FIRST_RUN_SECONDS = 15

# Shopping-partner rates change far less often than deal articles - once a
# day is plenty, and keeps requests to payback.de conservative (section 14).
SHOPPING_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
SHOPPING_REFRESH_FIRST_RUN_SECONDS = 30

# Single global daily-digest time for all users (Phase 7F.9). Not
# configurable per user yet, but send_daily_digest_for_user (bot/deals/digest.py)
# is factored so a later per-user schedule can call it directly without
# restructuring anything here.
DIGEST_TIME = datetime.time(8, 0, tzinfo=ZoneInfo("Europe/Berlin"))


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(BOT_COMMANDS)


async def _refresh_deals_job(context) -> None:
    inserted = await asyncio.to_thread(refresh_all_sources)
    if inserted:
        logging.getLogger(__name__).info("Scheduled deal refresh: %d new deal(s)", inserted)


async def _refresh_shopping_job(context) -> None:
    touched = await asyncio.to_thread(refresh_shopping_partners)
    if touched:
        logging.getLogger(__name__).info("Scheduled shopping-partner refresh: %d row(s) touched", touched)


def build_application(token: str) -> Application:
    """Builds the fully-wired Application (all handlers + scheduled job),
    without starting polling. Factored out of main() so tests can exercise
    the exact same registration/order via Application.process_update()
    instead of duplicating it - handler *order* is what makes the
    ConversationHandler-vs-menu_callback routing correct, so a test that
    doesn't build the real thing can't catch a regression there."""
    app = Application.builder().token(token).post_init(post_init).build()
    app.add_error_handler(handle_error)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profil", profil))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("zahlen", zahlen_entry))
    app.add_handler(CommandHandler("setup", setup))
    # /shopping ist im shopping_conversation ConversationHandler registriert
    # (weiter unten), nicht hier separat - es ist selbst ein Einstiegspunkt.
    app.add_handler(CommandHandler("hilfe", hilfe))
    app.add_handler(CommandHandler("deals", deals_entry))

    # /profil ist seit Phase 5 ein Hub (Karten/Programme/Präferenzen/Priorität/
    # Flughäfen). Toggle/Fertig-Mechanik unverändert aus Phase 1/2A, jetzt nur
    # typgescoped (siehe profile.py). pref_edit_conversation deckt die drei
    # Freitext-Felder ab (eigene Einstiegspunkte "prefedit:...").
    app.add_handler(CallbackQueryHandler(profil_callback, pattern=r"^(toggle:\d+|done)$"))
    app.add_handler(CallbackQueryHandler(profil_show_cards, pattern=r"^profilhub:karten$"))
    app.add_handler(CallbackQueryHandler(profil_show_programs, pattern=r"^profilhub:programme$"))
    app.add_handler(CallbackQueryHandler(show_reise, pattern=r"^profilhub:reise$"))
    app.add_handler(CallbackQueryHandler(show_prioritaet, pattern=r"^profilhub:prioritaet$"))
    app.add_handler(CallbackQueryHandler(show_flughaefen, pattern=r"^profilhub:flughaefen$"))
    app.add_handler(CallbackQueryHandler(prefpick_start, pattern=r"^prefpick:(travel_class|preferred_alliance)$"))
    app.add_handler(CallbackQueryHandler(prefset_callback, pattern=r"^prefset:[a-z_]+:[a-z_]+$"))
    app.add_handler(pref_edit_conversation)

    # ➕ Eigenes Programm hinzufügen (Phase 7.5, 14B) - eigener Einstiegspunkt
    # "customprog_new" (Button in der Programme-Ansicht), unabhängig vom
    # Profil-Toggle-Mechanismus.
    app.add_handler(custom_program_conversation)
    app.add_handler(CallbackQueryHandler(show_custom_programs, pattern=r"^customprog_manage$"))
    app.add_handler(CallbackQueryHandler(customprog_remove, pattern=r"^customprog_remove:\d+$"))

    # /punkte und "Neues Ziel anlegen" sind ConversationHandler mit eigenen
    # Einstiegspunkten (u. a. "menu:punkte" / "ziel_new"). Sie müssen VOR dem
    # generischen menu_callback registriert sein, da PTB pro Gruppe beim
    # ersten Treffer stoppt - sonst würde menu_callback "menu:punkte" zuerst
    # abfangen und die Conversation nie starten.
    app.add_handler(punkte_conversation)
    app.add_handler(ziel_new_conversation)

    # /ziele: reine Listenansicht + Aktivieren/Löschen, keine Conversation.
    app.add_handler(CommandHandler("ziele", ziele_view))
    app.add_handler(CallbackQueryHandler(ziele_view, pattern=r"^menu:ziele$"))
    app.add_handler(CallbackQueryHandler(ziel_activate, pattern=r"^ziel_activate:\d+$"))
    app.add_handler(CallbackQueryHandler(ziel_delete_prompt, pattern=r"^ziel_delete:\d+$"))
    app.add_handler(CallbackQueryHandler(ziel_delete_confirm, pattern=r"^ziel_delete_yes:\d+$"))
    app.add_handler(CallbackQueryHandler(ziel_delete_cancel, pattern=r"^ziel_delete_no$"))

    # /zahlen ("Womit zahlen?"): reine Inline-Button-Navigation (Kategorie ->
    # optionale Subkategorie -> Empfehlung), keine Conversation nötig. Auch
    # hier muss "menu:zahlen" VOR dem generischen menu_callback registriert
    # sein, sonst würde dieser es zuerst abfangen (siehe Kommentar oben).
    app.add_handler(CallbackQueryHandler(zahlen_entry, pattern=r"^menu:zahlen$"))
    app.add_handler(CallbackQueryHandler(zahlen_restart, pattern=r"^pay:restart$"))
    app.add_handler(CallbackQueryHandler(zahlen_category, pattern=r"^pay:category:[a-z_]+$"))
    app.add_handler(CallbackQueryHandler(zahlen_subcategory, pattern=r"^pay:subcategory:[a-z_]+:[a-z_]+$"))

    # 🔎 Einkauf optimieren (Phase 7.5): eigener ConversationHandler, freie
    # Texteingabe ist auf dessen States beschränkt (siehe shopping.py-Modul-
    # Docstring) und stört keinen anderen ConversationHandler. "menu:shopping"
    # muss vor dem generischen menu_callback stehen (gleicher Grund wie oben).
    app.add_handler(shopping_conversation)
    app.add_handler(CallbackQueryHandler(shopping_to_karte, pattern=r"^shop_karte$"))

    # /deals: gleiches Muster - "menu:deals" muss vor dem generischen
    # menu_callback registriert sein.
    app.add_handler(CallbackQueryHandler(deals_entry, pattern=r"^menu:deals$"))
    app.add_handler(CallbackQueryHandler(deals_refresh, pattern=r"^deals:refresh$"))
    app.add_handler(CallbackQueryHandler(deals_more, pattern=r"^deals:more:\d+$"))

    # Access-Requests (Phase 7I): "access:request" ist für JEDEN erreichbar
    # (auch nicht-autorisierte Nutzer - das ist der ganze Zweck), die
    # Freigabe-Entscheidung selbst prüft serverseitig is_admin() erneut.
    app.add_handler(CallbackQueryHandler(request_access, pattern=r"^access:request$"))
    app.add_handler(CallbackQueryHandler(decide_access, pattern=r"^access:(approve|reject):\d+$"))

    # Generischer Hauptmenü-Dispatcher: profil/hilfe/setup/status + "menu:home".
    # Muss zuletzt stehen.
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^menu:"))

    # Periodischer Deal-Refresh (reiner Datenabruf, verschickt an niemanden
    # eine Nachricht). Braucht das job-queue-Extra (siehe requirements.txt);
    # ohne installiertes Extra ist app.job_queue None und wir überspringen
    # das Scheduling sauber, statt einen harten Fehler zu werfen.
    if app.job_queue is not None:
        app.job_queue.run_repeating(
            _refresh_deals_job,
            interval=DEAL_REFRESH_INTERVAL_SECONDS,
            first=DEAL_REFRESH_FIRST_RUN_SECONDS,
        )
        # One personalized digest per day (08:00 Europe/Berlin). Sends
        # nothing to a user with no new relevant deals - see
        # bot/deals/digest.py.
        app.job_queue.run_daily(send_daily_digest_job, time=DIGEST_TIME)
        app.job_queue.run_repeating(
            _refresh_shopping_job,
            interval=SHOPPING_REFRESH_INTERVAL_SECONDS,
            first=SHOPPING_REFRESH_FIRST_RUN_SECONDS,
        )
    else:
        logging.getLogger(__name__).warning(
            "job_queue not available (python-telegram-bot[job-queue] extra missing) - "
            "deals will only refresh when a user taps 'Aktualisieren', and no daily digest will run."
        )

    return app


def main() -> None:
    init_db()
    app = build_application(BOT_TOKEN)
    app.run_polling()


if __name__ == "__main__":
    main()
