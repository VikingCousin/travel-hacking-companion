from telegram import Update
from telegram.ext import ContextTypes

from bot.menu import build_back_to_menu
from bot.whitelist import restricted

HELP_TEXT = (
    "❓ *Funktionen & Commands*\n\n"
    "✅ *Verfügbar:*\n"
    "/start – Willkommen & Hauptmenü\n"
    "/profil – Deine Karten & Loyalty-Programme auswählen/verwalten\n"
    "/status – Dein persönliches Dashboard: Punktestände & Ziel-Fortschritt\n"
    "/punkte – Punktestand manuell eintragen oder aktualisieren\n"
    "/ziele – Ziele anlegen, aktivieren oder löschen\n"
    "/zahlen – Regelbasierte Empfehlung, welche deiner Karten du wofür nutzt\n"
    "/deals – Relevante Travel-Deals aus öffentlichen Quellen, gefiltert auf dein Profil\n"
    "/setup – Kurze Einführung, wie die Einrichtung funktioniert\n"
    "/hilfe – Diese Übersicht\n\n"
    "Alle Funktionen erreichst du auch über das Hauptmenü (📊 👤 ➕ 🎯 💳 🔥 ⚙️ ❓). "
    "In mehrstufigen Eingaben (z. B. /punkte, /ziele) kannst du jederzeit mit "
    "❌ Abbrechen oder /abbrechen aussteigen."
)


@restricted
async def hilfe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        HELP_TEXT, parse_mode="Markdown", reply_markup=build_back_to_menu()
    )
