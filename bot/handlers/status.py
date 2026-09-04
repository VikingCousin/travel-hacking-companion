from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from bot.db import get_connection
from bot.deals.service import relevant_deals_for_user
from bot.handlers.preferences import PRIORITY_LABELS, TRAVEL_CLASS_LABELS
from bot.queries import (
    active_goal_with_progress,
    get_user_preferences,
    loyalty_programs_for_user,
    profile_counts,
)
from bot.validation import format_amount
from bot.whitelist import restricted

STATUS_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("👤 Profil", callback_data="menu:profil"),
            InlineKeyboardButton("➕ Punkte", callback_data="menu:punkte"),
        ],
        [
            InlineKeyboardButton("🎯 Ziele", callback_data="menu:ziele"),
            InlineKeyboardButton("🔥 Deals", callback_data="menu:deals"),
        ],
        [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")],
    ]
)


def _progress_bar(current: int, target: int, segments: int = 10) -> tuple[str, int]:
    if target <= 0:
        pct = 0
    else:
        pct = min(100, round(current / target * 100))
    filled = min(segments, round(pct / 100 * segments))
    bar = "█" * filled + "░" * (segments - filled)
    return bar, pct


def _build_status_text(programs, active_goal, counts, prefs, relevant_deal_count: int) -> str:
    lines = ["📊 *Dein Status*", ""]

    lines.append(f"💳 {counts['card']} Karten")
    lines.append(f"🎟 {counts['loyalty']} Programme")
    lines.append("")

    lines.append("💰 *Guthaben*")
    with_balance = [p for p in programs if p["balance"] is not None]
    without_balance = [p for p in programs if p["balance"] is None]
    if not programs:
        lines.append("Noch keine Loyalty-Programme im Profil. Richte sie über /profil ein.")
    elif not with_balance:
        lines.append("Noch keine Punktestände gepflegt.")
    else:
        for p in with_balance:
            emoji = p["emoji"] or "🔸"
            lines.append(f"{emoji} {p['name']}: {format_amount(p['balance'])} {p['unit_label']}")
    if without_balance:
        lines.append(
            f"ℹ️ {len(without_balance)} Programm(e) noch ohne Punktestand – trage sie über ➕ Punkte nach."
        )
    lines.append("")

    lines.append("🎯 *Ziel*")
    if active_goal is None:
        lines.append("Noch kein Ziel gesetzt. Leg eins über 🎯 Ziele an.")
    else:
        current = active_goal["balance"] or 0
        target = active_goal["target_amount"]
        bar, pct = _progress_bar(current, target)
        emoji = active_goal["emoji"] or "🎯"
        label = escape_markdown(active_goal["label"], version=1)
        lines.append(f"{emoji} {label}")
        lines.append(f"{format_amount(current)} / {format_amount(target)} {active_goal['unit_label']}")
        lines.append(f"{bar} {pct} %")
        if current >= target:
            lines.append("🎉 Ziel erreicht!")
    lines.append("")

    # Präferenzen sind alle optional - Zeilen nur zeigen, wenn wirklich etwas
    # hinterlegt ist, statt leere Felder als Textwand aufzulisten.
    # home_airport is free-typed by the user - escape before Markdown rendering.
    home_airport = escape_markdown(prefs["home_airport"], version=1) if prefs and prefs["home_airport"] else None
    travel_class = TRAVEL_CLASS_LABELS.get(prefs["travel_class"]) if prefs and prefs["travel_class"] else None
    priority = PRIORITY_LABELS.get(prefs["priority"]) if prefs and prefs["priority"] else None
    if home_airport or travel_class or priority:
        if home_airport:
            lines.append(f"📍 {home_airport}")
        if travel_class:
            lines.append(f"✈️ {travel_class}")
        if priority:
            lines.append(f"⭐ {priority}")
        lines.append("")

    if relevant_deal_count:
        lines.append(f"🔥 {relevant_deal_count} relevante Aktion(en) für dich")
    else:
        lines.append("🔥 Aktuell keine neuen relevanten Aktionen")

    return "\n".join(lines)


@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Reached either via CommandHandler (no callback_query) or via menu_callback's
    # _DISPATCH, which already answers the callback query before calling this.
    user_id = update.effective_user.id
    conn = get_connection()
    try:
        programs = loyalty_programs_for_user(conn, user_id)
        active_goal = active_goal_with_progress(conn, user_id)
        counts = profile_counts(conn, user_id)
        prefs = get_user_preferences(conn, user_id)
    finally:
        conn.close()

    relevant_deal_count = len(relevant_deals_for_user(user_id))

    text = _build_status_text(programs, active_goal, counts, prefs, relevant_deal_count)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=STATUS_KEYBOARD)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=STATUS_KEYBOARD)
