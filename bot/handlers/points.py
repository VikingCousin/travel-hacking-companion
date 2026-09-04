from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import get_connection
from bot.queries import loyalty_programs_for_user, upsert_point_balance
from bot.validation import format_amount, parse_amount
from bot.whitelist import restricted

CHOOSE_PROGRAM, AWAIT_VALUE = range(2)


def _format_program_button(program) -> str:
    emoji = program["emoji"] or "🔸"
    if program["balance"] is None:
        status = "noch kein Stand"
    else:
        status = f"{format_amount(program['balance'])} {program['unit_label']}"
    return f"{emoji} {program['name']} — {status}"


def _programs_keyboard(programs) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(_format_program_button(p), callback_data=f"punkte_prog:{p['id']}")]
        for p in programs
    ]
    buttons.append([InlineKeyboardButton("✅ Fertig", callback_data="punkte_done")])
    buttons.append([InlineKeyboardButton("❌ Abbrechen", callback_data="punkte_cancel")])
    return InlineKeyboardMarkup(buttons)


async def _show_program_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    conn = get_connection()
    try:
        programs = loyalty_programs_for_user(conn, update.effective_user.id)
    finally:
        conn.close()

    # Callback-triggered (menu button / "weiteren Stand ändern") edits the
    # existing message in place; only a fresh /punkte command needs a new one.
    send = update.callback_query.edit_message_text if update.callback_query else update.effective_message.reply_text

    if not programs:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👤 Profil einrichten", callback_data="menu:profil")]]
        )
        await send(
            "Du hast noch keine Loyalty-Programme in deinem Profil. "
            "Wähle sie zuerst über /profil aus.",
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    await send(
        "➕ *Punkte aktualisieren*\n\nWähle ein Programm, um den Stand einzutragen:",
        parse_mode="Markdown",
        reply_markup=_programs_keyboard(programs),
    )
    return CHOOSE_PROGRAM


@restricted
async def punkte_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    return await _show_program_picker(update, context)


@restricted
async def punkte_choose_program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    program_id = int(query.data.split(":", 1)[1])
    conn = get_connection()
    try:
        programs = {p["id"]: p for p in loyalty_programs_for_user(conn, update.effective_user.id)}
    finally:
        conn.close()

    program = programs.get(program_id)
    if program is None:
        await query.edit_message_text("Dieses Programm ist nicht mehr in deinem Profil.")
        return ConversationHandler.END

    context.user_data["punkte_program_id"] = program_id
    context.user_data["punkte_program_name"] = program["name"]
    context.user_data["punkte_unit_label"] = program["unit_label"]

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Abbrechen", callback_data="punkte_cancel")]])
    await query.edit_message_text(
        f"Wie viele {program['unit_label']} hat *{program['name']}* aktuell?\n"
        "(z. B. 8450, 8.450 oder 8 450)",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return AWAIT_VALUE


@restricted
async def punkte_receive_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = parse_amount(update.effective_message.text)
    if amount is None:
        await update.effective_message.reply_text(
            "❌ Das habe ich nicht als Zahl verstanden. Bitte gib eine positive Zahl ein "
            "(z. B. 8450, 8.450 oder 8 450)."
        )
        return AWAIT_VALUE

    program_id = context.user_data["punkte_program_id"]
    program_name = context.user_data["punkte_program_name"]
    unit_label = context.user_data["punkte_unit_label"]

    conn = get_connection()
    try:
        upsert_point_balance(conn, update.effective_user.id, program_id, amount)
        conn.commit()
    finally:
        conn.close()

    context.user_data.pop("punkte_program_id", None)
    context.user_data.pop("punkte_program_name", None)
    context.user_data.pop("punkte_unit_label", None)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Weiteren Stand ändern", callback_data="punkte_more")],
            [
                InlineKeyboardButton("📊 Status", callback_data="menu:status"),
                InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home"),
            ],
        ]
    )
    await update.effective_message.reply_text(
        f"✅ *Punktestand aktualisiert*\n\n{program_name}\n{format_amount(amount)} {unit_label}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return ConversationHandler.END


@restricted
async def punkte_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")]])
    await query.edit_message_text(
        "👍 Punktestände aktualisiert. Mit /status siehst du deinen Fortschritt.", reply_markup=keyboard
    )
    context.user_data.pop("punkte_program_id", None)
    context.user_data.pop("punkte_program_name", None)
    context.user_data.pop("punkte_unit_label", None)
    return ConversationHandler.END


@restricted
async def punkte_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Abgebrochen. Nichts wurde geändert.", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text("Abgebrochen. Nichts wurde geändert.", reply_markup=keyboard)
    context.user_data.pop("punkte_program_id", None)
    context.user_data.pop("punkte_program_name", None)
    context.user_data.pop("punkte_unit_label", None)
    return ConversationHandler.END


punkte_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("punkte", punkte_entry),
        CallbackQueryHandler(punkte_entry, pattern=r"^menu:punkte$"),
        CallbackQueryHandler(punkte_entry, pattern=r"^punkte_more$"),
    ],
    states={
        CHOOSE_PROGRAM: [
            CallbackQueryHandler(punkte_choose_program, pattern=r"^punkte_prog:\d+$"),
            CallbackQueryHandler(punkte_done, pattern=r"^punkte_done$"),
        ],
        AWAIT_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, punkte_receive_value),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(punkte_cancel, pattern=r"^punkte_cancel$"),
        CommandHandler("abbrechen", punkte_cancel),
    ],
    conversation_timeout=600,
)
