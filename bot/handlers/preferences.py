from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.helpers import escape_markdown

from bot.db import get_connection
from bot.queries import get_user_preferences, upsert_user_preference
from bot.whitelist import restricted

TRAVEL_CLASS_OPTIONS = [
    ("economy", "✈️ Economy"),
    ("premium_economy", "💺 Premium Economy"),
    ("business", "🥂 Business"),
    ("first", "👑 First"),
    ("flexible", "🔀 Flexibel"),
]
ALLIANCE_OPTIONS = [
    ("star_alliance", "⭐ Star Alliance"),
    ("skyteam", "🔺 SkyTeam"),
    ("oneworld", "🌐 OneWorld"),
    ("none", "🤷 Keine Präferenz"),
]
PRIORITY_OPTIONS = [
    ("miles", "✈️ Meilen maximieren"),
    ("cashback", "💰 Cashback maximieren"),
    ("status", "🏆 Status/Vorteile"),
    ("comfort", "🛋 Komfort"),
    ("balanced", "⚖️ Ausgewogen"),
]

TRAVEL_CLASS_LABELS = dict(TRAVEL_CLASS_OPTIONS)
ALLIANCE_LABELS = dict(ALLIANCE_OPTIONS)
PRIORITY_LABELS = dict(PRIORITY_OPTIONS)

TEXT_FIELD_PROMPTS = {
    "home_airport": ("📍 Heimatflughafen", "Wie lautet dein Heimatflughafen? (z. B. FRA, MUC, TXL)"),
    "preferred_airports": (
        "📍 Bevorzugte Flughäfen",
        "Welche Flughäfen bevorzugst du zusätzlich? (kommagetrennt, z. B. FRA, MUC)",
    ),
    "preferred_airlines": (
        "✈️ Bevorzugte Airlines",
        "Welche Airlines bevorzugst du? (kommagetrennt, z. B. Lufthansa, Turkish Airlines)",
    ),
}

AWAIT_TEXT_VALUE = 1

BACK_TO_PROFILE = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Zurück zum Profil", callback_data="menu:profil")]])


def _fmt(value: str | None) -> str:
    # travel_class/alliance/priority come from our own controlled label
    # dicts (safe either way); home_airport/preferred_airlines/
    # preferred_airports are free-typed by the user, so this must escape -
    # otherwise e.g. an airline name with an underscore would break Markdown
    # parsing (BadRequest) the next time this screen is rendered (Phase 7L).
    return escape_markdown(value, version=1) if value else "–"


async def _render_reise(update: Update) -> None:
    conn = get_connection()
    try:
        prefs = get_user_preferences(conn, update.effective_user.id)
    finally:
        conn.close()

    travel_class = TRAVEL_CLASS_LABELS.get(prefs["travel_class"]) if prefs and prefs["travel_class"] else None
    alliance = ALLIANCE_LABELS.get(prefs["preferred_alliance"]) if prefs and prefs["preferred_alliance"] else None
    airlines = prefs["preferred_airlines"] if prefs and prefs["preferred_airlines"] else None

    text = (
        "✈️ *Reisepräferenzen*\n\n"
        f"Reiseart: {_fmt(travel_class)}\n"
        f"Bevorzugte Allianz: {_fmt(alliance)}\n"
        f"Bevorzugte Airlines: {_fmt(airlines)}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Reiseart ändern", callback_data="prefpick:travel_class")],
            [InlineKeyboardButton("✏️ Allianz ändern", callback_data="prefpick:preferred_alliance")],
            [InlineKeyboardButton("✏️ Airlines ändern", callback_data="prefedit:preferred_airlines")],
            [InlineKeyboardButton("⬅️ Zurück", callback_data="menu:profil")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _render_prioritaet(update: Update) -> None:
    conn = get_connection()
    try:
        prefs = get_user_preferences(conn, update.effective_user.id)
    finally:
        conn.close()

    current = PRIORITY_LABELS.get(prefs["priority"]) if prefs and prefs["priority"] else None
    text = f"🎯 *Priorität*\n\nAktuell: {_fmt(current)}\n\nWas ist dir beim Travel Hacking am wichtigsten?"
    buttons = [[InlineKeyboardButton(label, callback_data=f"prefset:priority:{key}")] for key, label in PRIORITY_OPTIONS]
    buttons.append([InlineKeyboardButton("⬅️ Zurück", callback_data="menu:profil")])
    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


async def _render_flughaefen(update: Update) -> None:
    conn = get_connection()
    try:
        prefs = get_user_preferences(conn, update.effective_user.id)
    finally:
        conn.close()

    home = prefs["home_airport"] if prefs and prefs["home_airport"] else None
    others = prefs["preferred_airports"] if prefs and prefs["preferred_airports"] else None
    text = (
        "📍 *Flughäfen*\n\n"
        f"Heimatflughafen: {_fmt(home)}\n"
        f"Weitere bevorzugte Flughäfen: {_fmt(others)}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✏️ Heimatflughafen ändern", callback_data="prefedit:home_airport")],
            [InlineKeyboardButton("✏️ Weitere Flughäfen ändern", callback_data="prefedit:preferred_airports")],
            [InlineKeyboardButton("⬅️ Zurück", callback_data="menu:profil")],
        ]
    )
    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@restricted
async def show_reise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _render_reise(update)


@restricted
async def show_prioritaet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _render_prioritaet(update)


@restricted
async def show_flughaefen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _render_flughaefen(update)


@restricted
async def prefpick_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    field = query.data.split(":", 1)[1]
    options = TRAVEL_CLASS_OPTIONS if field == "travel_class" else ALLIANCE_OPTIONS
    title = "✈️ Reiseart" if field == "travel_class" else "🌐 Airline-Allianz"
    buttons = [[InlineKeyboardButton(label, callback_data=f"prefset:{field}:{key}")] for key, label in options]
    buttons.append([InlineKeyboardButton("⬅️ Zurück", callback_data="profilhub:reise")])
    await query.edit_message_text(f"{title}\n\nWähle eine Option:", reply_markup=InlineKeyboardMarkup(buttons))


@restricted
async def prefset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, field, value = query.data.split(":", 2)

    conn = get_connection()
    try:
        upsert_user_preference(conn, update.effective_user.id, field, value)
        conn.commit()
    finally:
        conn.close()

    if field == "priority":
        await _render_prioritaet(update)
    else:
        await _render_reise(update)


@restricted
async def edit_field_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    field = query.data.split(":", 1)[1]
    context.user_data["pref_edit_field"] = field
    title, prompt = TEXT_FIELD_PROMPTS[field]
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Abbrechen", callback_data="pref_cancel")]])
    await query.edit_message_text(f"{title}\n\n{prompt}", reply_markup=keyboard)
    return AWAIT_TEXT_VALUE


@restricted
async def edit_field_receive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data.pop("pref_edit_field", None)
    if field is None:
        return ConversationHandler.END

    value = update.effective_message.text.strip()[:200]
    if field == "home_airport":
        value = value.upper()

    conn = get_connection()
    try:
        upsert_user_preference(conn, update.effective_user.id, field, value)
        conn.commit()
    finally:
        conn.close()

    await update.effective_message.reply_text(f"✅ Gespeichert: {value}", reply_markup=BACK_TO_PROFILE)
    return ConversationHandler.END


@restricted
async def edit_field_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("pref_edit_field", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Abgebrochen.", reply_markup=BACK_TO_PROFILE)
    else:
        await update.effective_message.reply_text("Abgebrochen.", reply_markup=BACK_TO_PROFILE)
    return ConversationHandler.END


pref_edit_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(
            edit_field_start, pattern=r"^prefedit:(home_airport|preferred_airports|preferred_airlines)$"
        )
    ],
    states={
        AWAIT_TEXT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_receive)],
    },
    fallbacks=[
        CallbackQueryHandler(edit_field_cancel, pattern=r"^pref_cancel$"),
        CommandHandler("abbrechen", edit_field_cancel),
    ],
    conversation_timeout=600,
)
