from telegram import Update
from telegram.ext import ContextTypes

from bot.db import get_connection
from bot.menu import build_main_menu
from bot.whitelist import restricted

WELCOME_TEXT = (
    "👋 *Travel Hacking Companion*\n\n"
    "Dein persönlicher Assistent für Punkte, Meilen, Karten und Travel-Deals.\n\n"
    "📊 Behalte deinen Fortschritt im Blick\n"
    "🎯 Verfolge deine Reiseziele\n"
    "💳 Nutze die passende Karte\n"
    "🔥 Entdecke relevante Aktionen\n\n"
    "Was möchtest du tun?"
)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO users (telegram_id, first_name, username)
            VALUES (?, ?, ?)
            ON CONFLICT (telegram_id) DO UPDATE SET
                first_name = excluded.first_name,
                username = excluded.username
            """,
            (user.id, user.first_name, user.username),
        )
        conn.commit()
    finally:
        conn.close()

    await update.effective_message.reply_text(
        WELCOME_TEXT, parse_mode="Markdown", reply_markup=build_main_menu()
    )
