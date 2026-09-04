from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db import get_connection
from bot.queries import get_user_preferences, profile_counts, visible_programs
from bot.whitelist import restricted

TRAVEL_CLASS_LABELS = {
    "economy": "Economy",
    "premium_economy": "Premium Economy",
    "business": "Business",
    "first": "First",
    "flexible": "Flexibel",
}
PRIORITY_LABELS = {
    "miles": "Meilen maximieren",
    "cashback": "Cashback maximieren",
    "status": "Status/Vorteile",
    "comfort": "Komfort",
    "balanced": "Ausgewogen",
}


def _programs(conn, user_id: int, type_filter: str | None = None):
    # visible_programs = shared catalog + this user's own custom programs
    # only (14B.10) - never another user's custom entries.
    return visible_programs(conn, user_id, type_filter)


def _current_selection(conn, user_id: int, type_filter: str | None = None) -> set[int]:
    if type_filter:
        rows = conn.execute(
            """
            SELECT cp.program_id FROM card_profile cp
            JOIN programs p ON p.id = cp.program_id
            WHERE cp.user_id = ? AND p.type = ?
            """,
            (user_id, type_filter),
        ).fetchall()
    else:
        rows = conn.execute("SELECT program_id FROM card_profile WHERE user_id = ?", (user_id,)).fetchall()
    return {row["program_id"] for row in rows}


def _build_toggle_keyboard(programs, selected: set[int], type_filter: str | None) -> InlineKeyboardMarkup:
    buttons = []
    has_custom = False
    for program in programs:
        mark = "✅" if program["id"] in selected else "⬜️"
        # 👤-prefix distinguishes a user's own custom entry from the shared
        # catalog (14B.3) right in the picker, not just in a separate view.
        owner_tag = "👤 " if program["source"] == "user" else ""
        has_custom = has_custom or program["source"] == "user"
        buttons.append(
            [InlineKeyboardButton(f"{mark} {owner_tag}{program['name']}", callback_data=f"toggle:{program['id']}")]
        )
    if type_filter == "loyalty":
        buttons.append([InlineKeyboardButton("➕ Eigenes Programm hinzufügen", callback_data="customprog_new")])
        if has_custom:
            buttons.append([InlineKeyboardButton("👤 Eigene Programme verwalten", callback_data="customprog_manage")])
    buttons.append([InlineKeyboardButton("✅ Fertig", callback_data="done")])
    buttons.append([InlineKeyboardButton("⬅️ Zurück", callback_data="menu:profil")])
    return InlineKeyboardMarkup(buttons)


def _hub_label(base: str, detail: str | None) -> str:
    return f"{base} ({detail})" if detail else base


def _hub_keyboard(counts: dict, prefs) -> InlineKeyboardMarkup:
    travel_class = TRAVEL_CLASS_LABELS.get(prefs["travel_class"]) if prefs and prefs["travel_class"] else None
    priority = PRIORITY_LABELS.get(prefs["priority"]) if prefs and prefs["priority"] else None
    airport = prefs["home_airport"] if prefs and prefs["home_airport"] else None

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(_hub_label("💳 Karten", str(counts["card"]) if counts["card"] else None), callback_data="profilhub:karten")],
            [InlineKeyboardButton(_hub_label("🎟 Programme", str(counts["loyalty"]) if counts["loyalty"] else None), callback_data="profilhub:programme")],
            [InlineKeyboardButton(_hub_label("✈️ Reisepräferenzen", travel_class), callback_data="profilhub:reise")],
            [InlineKeyboardButton(_hub_label("🎯 Prioritäten", priority), callback_data="profilhub:prioritaet")],
            [InlineKeyboardButton(_hub_label("📍 Flughäfen", airport), callback_data="profilhub:flughaefen")],
            [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")],
        ]
    )


@restricted
async def profil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()

    conn = get_connection()
    try:
        counts = profile_counts(conn, update.effective_user.id)
        prefs = get_user_preferences(conn, update.effective_user.id)
    finally:
        conn.close()

    text = "👤 *Mein Profil*\n\nWähle einen Bereich:"
    keyboard = _hub_keyboard(counts, prefs)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _show_toggle_view(update: Update, context: ContextTypes.DEFAULT_TYPE, type_filter: str, title: str) -> None:
    user_id = update.effective_user.id
    conn = get_connection()
    try:
        programs = _programs(conn, user_id, type_filter)
        selected = _current_selection(conn, user_id, type_filter)
    finally:
        conn.close()

    context.user_data["profile_selection"] = selected
    context.user_data["profile_selection_type"] = type_filter

    text = (
        f"{title}\n\nTippe zum An-/Abwählen, dann 'Fertig'.\n\n"
        "✅ = aktiv in deinem Profil\n⬜️ = nicht aktiv"
    )
    if type_filter == "loyalty":
        text += "\n👤 = dein eigenes, manuell hinzugefügtes Programm"
    await update.callback_query.edit_message_text(text, reply_markup=_build_toggle_keyboard(programs, selected, type_filter))


@restricted
async def profil_show_cards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _show_toggle_view(update, context, "card", "💳 Karten")


@restricted
async def profil_show_programs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _show_toggle_view(update, context, "loyalty", "🎟 Programme")


@restricted
async def profil_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    selected: set[int] = context.user_data.setdefault("profile_selection", set())
    # Set by profil_show_cards/profil_show_programs. Scopes the save to just
    # that type so finishing the "Karten" view can never wipe out the user's
    # "Programme" selection (or vice versa) - each view only ever owns its
    # own slice of card_profile.
    type_filter = context.user_data.get("profile_selection_type")

    if query.data == "done":
        conn = get_connection()
        try:
            user_id = update.effective_user.id
            if type_filter:
                conn.execute(
                    """
                    DELETE FROM card_profile
                    WHERE user_id = ? AND program_id IN (SELECT id FROM programs WHERE type = ?)
                    """,
                    (user_id, type_filter),
                )
            else:
                conn.execute("DELETE FROM card_profile WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO card_profile (user_id, program_id) VALUES (?, ?)",
                [(user_id, program_id) for program_id in selected],
            )
            conn.commit()
            programs = _programs(conn, user_id, type_filter)
        finally:
            conn.close()

        names = [p["name"] for p in programs if p["id"] in selected]
        summary = ", ".join(names) if names else "keine ausgewählt"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Zurück zum Profil", callback_data="menu:profil")]])
        await query.edit_message_text(f"✅ Gespeichert: {summary}", reply_markup=keyboard)
        context.user_data.pop("profile_selection", None)
        context.user_data.pop("profile_selection_type", None)
        return

    program_id = int(query.data.split(":", 1)[1])
    if program_id in selected:
        selected.discard(program_id)
    else:
        selected.add(program_id)

    conn = get_connection()
    try:
        programs = _programs(conn, update.effective_user.id, type_filter)
    finally:
        conn.close()

    await query.edit_message_reply_markup(reply_markup=_build_toggle_keyboard(programs, selected, type_filter))
