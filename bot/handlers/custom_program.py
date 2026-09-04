"""'➕ Eigenes Programm hinzufügen' (Phase 7.5, 14B.2). Lets a user add a
rewards/membership program the shared catalog doesn't have (e.g. "Shell
ClubSmart") without needing an admin to curate it first. A name matching a
known alias or exact catalog entry (14B.4) is recognized deterministically
and simply added to the user's profile - no duplicate, no type question. An
unrecognized name becomes the user's own private program (14B.3): visible
and editable only by them (enforced in bot/queries.py, not just in the UI).
"""

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
from bot.queries import (
    create_custom_program,
    deactivate_custom_program,
    find_catalog_program_by_name,
    resolve_program_alias,
    user_custom_programs,
)
from bot.whitelist import restricted

AWAIT_NAME, AWAIT_TYPE, AWAIT_USAGE = range(3)

# All map to the DB's type='loyalty' (see bot/db.py's comment on the
# `programs.type` CHECK constraint for why) - the distinction is purely a
# clearer question for the user, not a different code path.
TYPE_OPTIONS = [
    ("loyalty", "🎟 Loyalty / Rewards"),
    ("card", "💳 Zahlungskarte"),
    ("membership", "🏷 Mitgliedschaft"),
    ("unsure", "❓ Nicht sicher"),
]
TYPE_TO_DB_TYPE = {"loyalty": "loyalty", "card": "card", "membership": "loyalty", "unsure": "loyalty"}

USAGE_OPTIONS = [
    ("tanken", "⛽ Tanken"),
    ("einkaufen", "🛒 Einkaufen"),
    ("reisen", "✈️ Reisen"),
    ("hotels", "🏨 Hotels"),
    ("gastronomie", "🍽 Gastronomie"),
    ("online", "🌐 Online"),
    ("andere", "➕ Andere"),
]

CANCEL_KEYBOARD = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Abbrechen", callback_data="customprog_cancel")]])
BACK_TO_PROFILE = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Zurück zum Profil", callback_data="menu:profil")]])


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ("customprog_name", "customprog_type"):
        context.user_data.pop(key, None)


async def _add_to_profile(conn, user_id: int, program_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO card_profile (user_id, program_id) VALUES (?, ?)", (user_id, program_id)
    )
    conn.commit()


@restricted
async def customprog_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "➕ *Eigenes Programm hinzufügen*\n\nWie heißt deine Karte oder dein Rewards-Programm?\n\n"
        "z. B. \"Shell ClubSmart\"",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD,
    )
    return AWAIT_NAME


@restricted
async def customprog_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.effective_message.text.strip()[:80]
    if not name:
        await update.effective_message.reply_text("Bitte gib einen Namen ein.")
        return AWAIT_NAME

    user_id = update.effective_user.id
    conn = get_connection()
    try:
        # 14B.4: deterministic recognition only - alias table first, then an
        # exact (case-insensitive) catalog match for names not covered by an
        # alias. No fuzzy matching, so a near-miss becomes the user's own
        # program rather than risking a wrong merge.
        canonical_name = resolve_program_alias(name)
        catalog_row = None
        if canonical_name:
            catalog_row = conn.execute(
                "SELECT id, name FROM programs WHERE source='catalog' AND name = ?", (canonical_name,)
            ).fetchone()
        if catalog_row is None:
            catalog_row = find_catalog_program_by_name(conn, name)

        if catalog_row is not None:
            await _add_to_profile(conn, user_id, catalog_row["id"])
            safe_name = escape_markdown(catalog_row["name"], version=1)
            await update.effective_message.reply_text(
                f"✅ *{safe_name}* ist bereits als verifiziertes Programm bekannt und wurde zu deinem Profil hinzugefügt.",
                parse_mode="Markdown",
                reply_markup=BACK_TO_PROFILE,
            )
            _clear_state(context)
            return ConversationHandler.END
    finally:
        conn.close()

    context.user_data["customprog_name"] = name
    safe_name = escape_markdown(name, version=1)
    buttons = [[InlineKeyboardButton(label, callback_data=f"customprog_type:{key}")] for key, label in TYPE_OPTIONS]
    buttons.append([InlineKeyboardButton("❌ Abbrechen", callback_data="customprog_cancel")])
    await update.effective_message.reply_text(
        f"*{safe_name}* kenne ich noch nicht als verifiziertes Programm.\n\nWelcher Typ passt am besten?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return AWAIT_TYPE


@restricted
async def customprog_receive_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    type_key = query.data.split(":", 1)[1]
    db_type = TYPE_TO_DB_TYPE[type_key]
    context.user_data["customprog_type"] = db_type

    if db_type != "loyalty":
        return await _finish_custom_program(update, context, usage_context=None, edit=True)

    buttons = [[InlineKeyboardButton(label, callback_data=f"customprog_usage:{key}")] for key, label in USAGE_OPTIONS]
    buttons.append([InlineKeyboardButton("⏭ Ohne Kategorie", callback_data="customprog_usage:skip")])
    await query.edit_message_text(
        "Wo nutzt du es hauptsächlich? (optional)", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return AWAIT_USAGE


@restricted
async def customprog_receive_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    usage_key = update.callback_query.data.split(":", 1)[1]
    usage_context = None if usage_key in ("skip",) else dict(USAGE_OPTIONS).get(usage_key)
    return await _finish_custom_program(update, context, usage_context=usage_context, edit=True)


async def _finish_custom_program(update: Update, context: ContextTypes.DEFAULT_TYPE, usage_context: str | None, edit: bool) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    name = context.user_data.get("customprog_name")
    db_type = context.user_data.get("customprog_type")
    if not name or not db_type:
        # Defensive: state was lost (e.g. conversation_timeout) - fail
        # cleanly rather than crashing on a missing user_data key.
        text = "Die Sitzung ist abgelaufen. Bitte starte mit ➕ Eigenes Programm hinzufügen erneut."
        if query:
            await query.edit_message_text(text, reply_markup=BACK_TO_PROFILE)
        else:
            await update.effective_message.reply_text(text, reply_markup=BACK_TO_PROFILE)
        _clear_state(context)
        return ConversationHandler.END

    user_id = update.effective_user.id
    conn = get_connection()
    try:
        program_id = create_custom_program(conn, user_id, name, db_type, usage_context)
        conn.commit()
        await _add_to_profile(conn, user_id, program_id)
    finally:
        conn.close()

    safe_name = escape_markdown(name, version=1)
    text = f"✅ *{safe_name}* wurde als dein eigenes Programm gespeichert und zu deinem Profil hinzugefügt."
    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=BACK_TO_PROFILE)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=BACK_TO_PROFILE)

    _clear_state(context)
    return ConversationHandler.END


@restricted
async def customprog_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_state(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Abgebrochen.", reply_markup=BACK_TO_PROFILE)
    else:
        await update.effective_message.reply_text("Abgebrochen.", reply_markup=BACK_TO_PROFILE)
    return ConversationHandler.END


def _custom_programs_view(programs) -> tuple[str, InlineKeyboardMarkup]:
    if not programs:
        text = "👤 *Eigene Programme*\n\nDu hast noch keine eigenen Programme hinzugefügt."
    else:
        lines = ["👤 *Eigene Programme*", ""]
        for p in programs:
            type_label = "Zahlungskarte" if p["type"] == "card" else "Loyalty/Rewards"
            usage = f" · {p['usage_context']}" if p["usage_context"] else ""
            lines.append(f"• {escape_markdown(p['name'], version=1)} ({type_label}{usage})")
        text = "\n".join(lines)

    buttons = [
        [InlineKeyboardButton(f"🗑 {p['name'][:24]} entfernen", callback_data=f"customprog_remove:{p['id']}")]
        for p in programs
    ]
    buttons.append([InlineKeyboardButton("➕ Neues Programm", callback_data="customprog_new")])
    buttons.append([InlineKeyboardButton("⬅️ Zurück", callback_data="menu:profil")])
    return text, InlineKeyboardMarkup(buttons)


@restricted
async def show_custom_programs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    conn = get_connection()
    try:
        programs = user_custom_programs(conn, update.effective_user.id)
    finally:
        conn.close()
    text, keyboard = _custom_programs_view(programs)
    await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@restricted
async def customprog_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    program_id = int(query.data.split(":", 1)[1])
    user_id = update.effective_user.id

    conn = get_connection()
    try:
        # Ownership re-checked server-side inside deactivate_custom_program -
        # never trusts that a callback's program_id actually belongs to the
        # tapping user.
        deactivate_custom_program(conn, user_id, program_id)
        conn.commit()
        programs = user_custom_programs(conn, user_id)
    finally:
        conn.close()

    text, keyboard = _custom_programs_view(programs)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


custom_program_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(customprog_start, pattern=r"^customprog_new$")],
    states={
        AWAIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, customprog_receive_name)],
        AWAIT_TYPE: [CallbackQueryHandler(customprog_receive_type, pattern=r"^customprog_type:(loyalty|card|membership|unsure)$")],
        AWAIT_USAGE: [CallbackQueryHandler(customprog_receive_usage, pattern=r"^customprog_usage:[a-z]+$")],
    },
    fallbacks=[
        CallbackQueryHandler(customprog_cancel, pattern=r"^customprog_cancel$"),
        CommandHandler("abbrechen", customprog_cancel),
    ],
    conversation_timeout=600,
)
