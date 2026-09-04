from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MENU_ROWS = [
    [("📊 Status", "menu:status"), ("👤 Profil", "menu:profil")],
    [("➕ Punkte", "menu:punkte"), ("🎯 Ziele", "menu:ziele")],
    [("💳 Womit zahlen?", "menu:zahlen"), ("🔎 Einkauf optimieren", "menu:shopping")],
    [("🔥 Deals & Aktionen", "menu:deals"), ("⚙️ Setup", "menu:setup")],
    [("❓ Hilfe", "menu:hilfe")],
]

# key -> (Anzeigename, Phase, in der die Funktion kommt)
# Alle Hauptmenü-Funktionen sind seit Phase 4 live - aktuell leer, aber als
# Mechanismus für künftige Phasen (z. B. Phase 8) erhalten.
COMING_SOON: dict[str, tuple[str, str]] = {}


def build_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(label, callback_data=data) for label, data in row]
        for row in MENU_ROWS
    ]
    return InlineKeyboardMarkup(keyboard)


def build_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")]])


def coming_soon_text(key: str) -> str:
    title, phase = COMING_SOON[key]
    return f"{title}\n\n🚧 Kommt in {phase} – noch nicht implementiert."


MENU_INTRO_TEXT = "Was möchtest du tun?"
