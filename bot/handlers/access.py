"""Access-request system (Phase 7I). ALLOWED_USER_IDS (.env) stays the
bootstrap/admin allowlist, untouched by this module - it is never written to
here. A non-admin becomes authorized only via an 'approved' row in
access_requests, decided exclusively by an admin (checked server-side on
every decision, never trusted from callback data alone). No public request
handler is @restricted - by definition, the people using it aren't
authorized yet - but the *decision* handler independently re-checks
is_admin() before doing anything, which is what actually matters here.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from bot.config import ALLOWED_USER_IDS
from bot.db import get_connection
from bot.whitelist import is_admin

logger = logging.getLogger(__name__)


def _display_name(user) -> str:
    # first_name/username are set by the (as-yet unauthorized) requester
    # themselves - anyone can trigger this flow, so this must be escaped
    # before being rendered with parse_mode="Markdown" to the admin (Phase 7L).
    raw = f"@{user.username}" if user.username else (user.first_name or f"User {user.id}")
    return escape_markdown(raw, version=1)


async def request_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT status FROM access_requests WHERE telegram_id = ?", (user.id,)
        ).fetchone()
        if existing and existing["status"] == "pending":
            await query.edit_message_text("🕐 Deine Anfrage liegt bereits vor und wartet auf Freigabe.")
            return
        if existing and existing["status"] == "approved":
            await query.edit_message_text("✅ Du hast bereits Zugriff. Nutze /start, um loszulegen.")
            return

        conn.execute(
            """
            INSERT INTO access_requests (telegram_id, first_name, username, status, requested_at)
            VALUES (?, ?, ?, 'pending', datetime('now'))
            ON CONFLICT (telegram_id) DO UPDATE SET
                status = 'pending',
                first_name = excluded.first_name,
                username = excluded.username,
                requested_at = datetime('now'),
                decided_at = NULL,
                decided_by = NULL
            """,
            (user.id, user.first_name, user.username),
        )
        conn.commit()
    finally:
        conn.close()

    await query.edit_message_text(
        "🙋 Anfrage gesendet.\n\nDu wirst benachrichtigt, sobald sie bearbeitet wurde."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Freigeben", callback_data=f"access:approve:{user.id}"),
                InlineKeyboardButton("❌ Ablehnen", callback_data=f"access:reject:{user.id}"),
            ]
        ]
    )
    text = f"🔐 *Neue Zugangsanfrage*\n\n{_display_name(user)}"
    for admin_id in ALLOWED_USER_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode="Markdown", reply_markup=keyboard)
        except TelegramError:
            logger.exception("Could not notify admin %s about a new access request", admin_id)


async def decide_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    admin = update.effective_user

    # Server-side authorization check - callback_data is never trusted on its
    # own. A requester can never approve themselves: they are, by
    # definition, not in ALLOWED_USER_IDS (otherwise they'd already have
    # access and never see the request flow) - checked explicitly anyway as
    # defense in depth.
    if admin is None or not is_admin(admin.id):
        await query.answer("Nicht autorisiert.", show_alert=True)
        return
    await query.answer()

    _, action, requester_id_str = query.data.split(":", 2)
    requester_id = int(requester_id_str)
    if requester_id == admin.id:
        await query.edit_message_text("⚠️ Ungültige Anfrage.")
        return
    approve = action == "approve"

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE access_requests SET status = ?, decided_at = datetime('now'), decided_by = ? WHERE telegram_id = ?",
            ("approved" if approve else "rejected", admin.id, requester_id),
        )
        conn.commit()
    finally:
        conn.close()

    decision_note = "\n\n✅ Freigegeben." if approve else "\n\n❌ Abgelehnt."
    await query.edit_message_text((query.message.text or "") + decision_note)

    try:
        if approve:
            await context.bot.send_message(
                chat_id=requester_id,
                text="✅ Du hast jetzt Zugriff auf den Travel Hacking Companion.\n\nNutze /start, um loszulegen.",
            )
        else:
            await context.bot.send_message(
                chat_id=requester_id, text="❌ Deine Zugangsanfrage wurde abgelehnt."
            )
    except TelegramError:
        logger.exception("Could not notify requester %s about the access decision", requester_id)
