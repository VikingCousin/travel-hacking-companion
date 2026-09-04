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
from bot.queries import all_goals, create_goal, delete_goal, loyalty_programs_for_user, set_active_goal
from bot.validation import format_amount, parse_amount
from bot.whitelist import restricted

AWAIT_LABEL, AWAIT_PROGRAM, AWAIT_AMOUNT = range(3)


def _goals_text_and_keyboard(goals):
    if not goals:
        text = "🎯 *Deine Ziele*\n\nDu hast noch keine Ziele. Leg dein erstes an!"
    else:
        lines = ["🎯 *Deine Ziele*\n"]
        for g in goals:
            marker = "⭐" if g["is_active"] else "▫️"
            target = format_amount(g["target_amount"])
            label = escape_markdown(g["label"], version=1)
            lines.append(f"{marker} {label}\n   {g['program_name']}: Ziel {target} {g['unit_label']}")
        text = "\n\n".join(lines)

    buttons = []
    for g in goals:
        row = []
        if not g["is_active"]:
            row.append(InlineKeyboardButton(f"⭐ Aktivieren: {g['label'][:20]}", callback_data=f"ziel_activate:{g['id']}"))
        row.append(InlineKeyboardButton(f"🗑 {g['label'][:20]}", callback_data=f"ziel_delete:{g['id']}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("➕ Neues Ziel", callback_data="ziel_new")])
    buttons.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return text, InlineKeyboardMarkup(buttons)


@restricted
async def ziele_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()

    conn = get_connection()
    try:
        goals = all_goals(conn, update.effective_user.id)
    finally:
        conn.close()

    text, keyboard = _goals_text_and_keyboard(goals)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


@restricted
async def ziel_activate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    goal_id = int(query.data.split(":", 1)[1])

    conn = get_connection()
    try:
        set_active_goal(conn, update.effective_user.id, goal_id)
        conn.commit()
        goals = all_goals(conn, update.effective_user.id)
    finally:
        conn.close()

    text, keyboard = _goals_text_and_keyboard(goals)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


@restricted
async def ziel_delete_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    goal_id = int(query.data.split(":", 1)[1])

    conn = get_connection()
    try:
        goals = {g["id"]: g for g in all_goals(conn, update.effective_user.id)}
    finally:
        conn.close()

    goal = goals.get(goal_id)
    if goal is None:
        await query.edit_message_text("Dieses Ziel existiert nicht mehr.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ja, löschen", callback_data=f"ziel_delete_yes:{goal_id}"),
                InlineKeyboardButton("❌ Nein", callback_data="ziel_delete_no"),
            ]
        ]
    )
    await query.edit_message_text(
        f"Sicher, dass du '{goal['label']}' löschen willst?", reply_markup=keyboard
    )


@restricted
async def ziel_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    goal_id = int(query.data.split(":", 1)[1])

    conn = get_connection()
    try:
        delete_goal(conn, update.effective_user.id, goal_id)
        conn.commit()
        goals = all_goals(conn, update.effective_user.id)
    finally:
        conn.close()

    text, keyboard = _goals_text_and_keyboard(goals)
    await query.edit_message_text(f"🗑 Ziel gelöscht.\n\n{text}", parse_mode="Markdown", reply_markup=keyboard)


@restricted
async def ziel_delete_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ziele_view(update, context)


# --- Neues Ziel anlegen (ConversationHandler: Label -> Programm -> Menge) ---


@restricted
async def ziel_new_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    conn = get_connection()
    try:
        programs = loyalty_programs_for_user(conn, update.effective_user.id)
    finally:
        conn.close()

    if not programs:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("👤 Profil einrichten", callback_data="menu:profil")]]
        )
        await query.edit_message_text(
            "Du hast noch keine Loyalty-Programme in deinem Profil. "
            "Wähle sie zuerst über /profil aus.",
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Abbrechen", callback_data="ziel_cancel")]])
    await query.edit_message_text(
        "🎯 *Neues Ziel*\n\nWie soll dein Ziel heißen? (z. B. 'Business Class nach Dubai')",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return AWAIT_LABEL


@restricted
async def ziel_receive_label(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label = update.effective_message.text.strip()
    if not label:
        await update.effective_message.reply_text("Bitte gib einen Namen für dein Ziel ein.")
        return AWAIT_LABEL

    context.user_data["ziel_label"] = label

    conn = get_connection()
    try:
        programs = loyalty_programs_for_user(conn, update.effective_user.id)
    finally:
        conn.close()

    buttons = [
        [InlineKeyboardButton(f"{p['emoji'] or '🔸'} {p['name']}", callback_data=f"ziel_prog:{p['id']}")]
        for p in programs
    ]
    buttons.append([InlineKeyboardButton("❌ Abbrechen", callback_data="ziel_cancel")])

    await update.effective_message.reply_text(
        "Für welches Programm ist das Ziel?", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return AWAIT_PROGRAM


@restricted
async def ziel_receive_program(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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

    context.user_data["ziel_program_id"] = program_id
    context.user_data["ziel_program_name"] = program["name"]
    context.user_data["ziel_unit_label"] = program["unit_label"]

    await query.edit_message_text(
        f"Wie viele {program['unit_label']} braucht ihr für '{context.user_data['ziel_label']}'?\n"
        "(z. B. 40000, 40.000 oder 40 000)"
    )
    return AWAIT_AMOUNT


@restricted
async def ziel_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = parse_amount(update.effective_message.text)
    if amount is None or amount == 0:
        await update.effective_message.reply_text(
            "❌ Das habe ich nicht als Zahl verstanden. Bitte gib eine positive Zahl ein "
            "(z. B. 40000, 40.000 oder 40 000)."
        )
        return AWAIT_AMOUNT

    label = context.user_data.pop("ziel_label")
    program_id = context.user_data.pop("ziel_program_id")
    program_name = context.user_data.pop("ziel_program_name")
    unit_label = context.user_data.pop("ziel_unit_label")

    conn = get_connection()
    try:
        _, auto_activated = create_goal(conn, update.effective_user.id, program_id, label, amount)
    finally:
        conn.close()

    activation_note = "\n\n⭐ Automatisch als aktives Ziel gesetzt (dein erstes Ziel)." if auto_activated else (
        "\n\nDieses Ziel ist noch nicht aktiv. Setze es über /ziele als aktiv, wenn du magst."
    )
    await update.effective_message.reply_text(
        f"✅ Ziel gespeichert: {label} ({program_name}, {format_amount(amount)} {unit_label}){activation_note}"
    )
    return ConversationHandler.END


@restricted
async def ziel_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("ziel_label", "ziel_program_id", "ziel_program_name", "ziel_unit_label"):
        context.user_data.pop(key, None)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Abgebrochen. Kein Ziel wurde angelegt.", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text("Abgebrochen. Kein Ziel wurde angelegt.", reply_markup=keyboard)
    return ConversationHandler.END


ziel_new_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(ziel_new_start, pattern=r"^ziel_new$")],
    states={
        AWAIT_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, ziel_receive_label)],
        AWAIT_PROGRAM: [CallbackQueryHandler(ziel_receive_program, pattern=r"^ziel_prog:\d+$")],
        AWAIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ziel_receive_amount)],
    },
    fallbacks=[
        CallbackQueryHandler(ziel_cancel, pattern=r"^ziel_cancel$"),
        CommandHandler("abbrechen", ziel_cancel),
    ],
    conversation_timeout=600,
)
