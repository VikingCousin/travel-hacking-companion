from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.help import hilfe
from bot.handlers.profile import profil
from bot.handlers.setup import setup
from bot.handlers.status import status
from bot.menu import MENU_INTRO_TEXT, build_back_to_menu, build_main_menu, coming_soon_text
from bot.whitelist import restricted

# Hauptmenü-Buttons, die auf einen bereits gebauten Flow zeigen (unverändert wiederverwendet).
# "punkte" (ConversationHandler) und "ziele" (eigene View) werden NICHT hier
# dispatcht, sondern haben in bot/main.py eigene, vorrangig registrierte
# Handler für "menu:punkte" / "menu:ziele" - diese Funktion hier sieht ihre
# Callbacks nie, weil PTB pro Gruppe beim ersten Treffer stoppt.
_DISPATCH = {
    "profil": profil,
    "hilfe": hilfe,
    "setup": setup,
    "status": status,
}


@restricted
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]

    if key == "home":
        await query.edit_message_text(MENU_INTRO_TEXT, reply_markup=build_main_menu())
        return

    handler = _DISPATCH.get(key)
    if handler is not None:
        await handler(update, context)
        return

    await query.edit_message_text(coming_soon_text(key), reply_markup=build_back_to_menu())


@restricted
async def coming_soon_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    command = update.effective_message.text.split()[0].lstrip("/").split("@")[0].lower()
    await update.effective_message.reply_text(
        coming_soon_text(command), reply_markup=build_back_to_menu()
    )
