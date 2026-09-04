from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.whitelist import restricted

SETUP_TEXT = (
    "⚙️ *Einrichtung*\n\n"
    "So richtest du deinen Travel Hacking Companion ein – alles über /profil, "
    "in eigenen Bereichen:\n\n"
    "1️⃣ *💳 Karten*\n"
    "Welche Zahlungskarten du nutzt (z. B. Trade Republic, Payback Amex, Wise, Revolut).\n\n"
    "2️⃣ *🎟 Programme*\n"
    "Deine Loyalty-Programme (z. B. Payback, Miles & More).\n\n"
    "3️⃣ *📍 Flughäfen & ✈️ Reisepräferenzen* (optional)\n"
    "Heimatflughafen, bevorzugte Airlines/Allianz und Reiseart – hilft bei künftigen "
    "personalisierten Empfehlungen.\n\n"
    "4️⃣ *🎯 Priorität* (optional)\n"
    "Was dir am wichtigsten ist: Meilen, Cashback, Status, Komfort oder ausgewogen.\n\n"
    "5️⃣ *➕ Punkte & 🎯 Ziele* (optional)\n"
    "Punktestände und Sparziele kannst du jederzeit später nachtragen – für den Start "
    "reichen Karten und Programme.\n\n"
    "Kein Login, kein Scraping: Der Bot greift nie automatisiert auf deine echten "
    "Konten zu – alles wird von dir manuell gepflegt.\n\n"
    "👉 Starte am besten direkt mit deinem Profil:"
)


@restricted
async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Profil jetzt einrichten", callback_data="menu:profil")],
            [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")],
        ]
    )
    await update.effective_message.reply_text(SETUP_TEXT, parse_mode="Markdown", reply_markup=keyboard)
