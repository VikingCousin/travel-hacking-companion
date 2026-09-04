from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db import get_connection
from bot.queries import recommendation_rules_for, user_cards
from bot.recommendation_engine import recommend
from bot.whitelist import restricted

# key, label, subcategories ([(sub_key, sub_label), ...] or None)
CATEGORIES = [
    ("restaurant", "🍽 Restaurant", None),
    ("supermarkt", "🛒 Supermarkt", None),
    ("shopping", "🛍 Shopping", [("stationaer", "Stationär"), ("online", "Online")]),
    ("online", "🌐 Online-Kauf", None),
    ("flug", "✈️ Flug", [("airline", "Direkt bei Airline"), ("reiseportal", "Reiseportal"), ("sonstiges", "Sonstiges")]),
    ("hotel", "🏨 Hotel", None),
    ("bahn", "🚆 Bahn / ÖPNV", None),
    ("tanken", "⛽ Tanken", None),
    ("ausland", "🌍 Ausland", [("karte", "Kartenzahlung"), ("bargeld", "Bargeldabhebung")]),
    ("bargeld", "💶 Bargeld / ATM", None),
    ("sonstiges", "📦 Sonstiges", None),
]
CATEGORY_MAP = {key: (key, label, subcats) for key, label, subcats in CATEGORIES}

ENTRY_TEXT = "💳 *Womit möchtest du zahlen?*\n\nWähle die Situation:"

GENERIC_DISCLAIMER = (
    "Kartenkonditionen und Gebühren können sich ändern. Prüfe bei größeren "
    "Zahlungen im Zweifel die aktuellen Konditionen."
)


def _category_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for key, label, _ in CATEGORIES:
        row.append(InlineKeyboardButton(label, callback_data=f"pay:category:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return InlineKeyboardMarkup(buttons)


def _subcategory_keyboard(category_key: str, subcats) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"pay:subcategory:{category_key}:{sub_key}")]
        for sub_key, label in subcats
    ]
    buttons.append([InlineKeyboardButton("🔄 Andere Situation", callback_data="pay:restart")])
    buttons.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return InlineKeyboardMarkup(buttons)


def _result_keyboard(with_profile_hint: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if with_profile_hint:
        rows.append([InlineKeyboardButton("👤 Profil prüfen", callback_data="menu:profil")])
    rows.append([InlineKeyboardButton("🔄 Andere Situation", callback_data="pay:restart")])
    rows.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def _format_recommendation(category_label: str, subcategory_label: str | None, recs) -> str:
    medals = ["🥇", "🥈", "🥉"]
    lines = ["💳 *Empfehlung*", ""]
    context_label = f"{category_label} → {subcategory_label}" if subcategory_label else category_label
    lines.append(f"_{context_label}_")
    lines.append("")

    primary = recs[0]
    emoji = primary.emoji or "💳"
    lines.append(f"{medals[0]} {emoji} *{primary.name}*")
    lines.append("")
    lines.append("Warum?")
    lines.append("• Du hast die Karte in deinem Profil aktiviert.")
    if primary.reason:
        lines.append(f"• {primary.reason}")
    lines.append("")

    if len(recs) > 1:
        alt = recs[1]
        alt_emoji = alt.emoji or "💳"
        lines.append("Alternative:")
        lines.append(f"{medals[1]} {alt_emoji} {alt.name}")
        if alt.reason:
            lines.append(alt.reason)
        lines.append("")

    warnings = []
    for r in recs:
        if r.warning and r.warning not in warnings:
            warnings.append(r.warning)

    lines.append("⚠️ *Hinweis:*")
    for w in warnings:
        lines.append(w)
    lines.append(GENERIC_DISCLAIMER)

    return "\n".join(lines)


async def _show_category_picker(update: Update) -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(
            ENTRY_TEXT, parse_mode="Markdown", reply_markup=_category_keyboard()
        )
    else:
        await update.effective_message.reply_text(
            ENTRY_TEXT, parse_mode="Markdown", reply_markup=_category_keyboard()
        )


async def _show_recommendation(
    update: Update, user_id: int, category_key: str, subcategory_key: str | None,
    category_label: str, subcategory_label: str | None,
) -> None:
    conn = get_connection()
    try:
        cards = user_cards(conn, user_id)
        rule_rows = recommendation_rules_for(conn, category_key, subcategory_key) if cards else []
    finally:
        conn.close()

    if not cards:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👤 Profil einrichten", callback_data="menu:profil")]]
        )
        await update.callback_query.edit_message_text(
            "💳 Noch keine Karten hinterlegt.\n\nRichte zuerst dein Kartenprofil ein.",
            reply_markup=keyboard,
        )
        return

    recs = recommend(cards, rule_rows)

    if not recs:
        await update.callback_query.edit_message_text(
            "🤔 *Keine eindeutige Empfehlung*\n\n"
            "Für diese Situation habe ich mit deinen aktuell hinterlegten Karten "
            "noch keine passende Regel.",
            parse_mode="Markdown",
            reply_markup=_result_keyboard(with_profile_hint=True),
        )
        return

    text = _format_recommendation(category_label, subcategory_label, recs)
    await update.callback_query.edit_message_text(
        text, parse_mode="Markdown", reply_markup=_result_keyboard()
    )


@restricted
async def zahlen_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await _show_category_picker(update)


@restricted
async def zahlen_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _show_category_picker(update)


@restricted
async def zahlen_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    category_key = query.data.split(":", 2)[2]
    category = CATEGORY_MAP.get(category_key)
    if category is None:
        await _show_category_picker(update)
        return

    key, label, subcats = category
    if subcats:
        await query.edit_message_text(
            f"💳 *{label}*\n\nWähle die genaue Situation:",
            parse_mode="Markdown",
            reply_markup=_subcategory_keyboard(key, subcats),
        )
        return

    await _show_recommendation(update, update.effective_user.id, key, None, label, None)


@restricted
async def zahlen_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, _, category_key, subcat_key = query.data.split(":", 3)
    category = CATEGORY_MAP.get(category_key)
    if category is None:
        await _show_category_picker(update)
        return

    key, label, subcats = category
    subcat_label = dict(subcats or []).get(subcat_key, subcat_key)
    await _show_recommendation(update, update.effective_user.id, key, subcat_key, label, subcat_label)
