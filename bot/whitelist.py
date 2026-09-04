from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import ALLOWED_USER_IDS
from bot.db import get_connection

DENIED_TEXT = "🔐 Dieser Bot ist privat.\n\nDu hast aktuell keinen Zugriff."


def is_admin(user_id: int) -> bool:
    """ALLOWED_USER_IDS (.env) is the bootstrap/admin allowlist - only admins
    can approve or reject access requests (see bot/handlers/access.py)."""
    return user_id in ALLOWED_USER_IDS


def is_authorized(user_id: int) -> bool:
    """Admins are always authorized. Anyone else needs an approved row in
    access_requests (Phase 7I) - checked fresh on every call, never cached,
    so a rejection/approval takes effect immediately."""
    if user_id in ALLOWED_USER_IDS:
        return True
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM access_requests WHERE telegram_id = ? AND status = 'approved'", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def _denied_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🙋 Zugang anfragen", callback_data="access:request")]])


def restricted(handler):
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not is_authorized(user.id):
            if update.effective_message:
                await update.effective_message.reply_text(DENIED_TEXT, reply_markup=_denied_keyboard())
            return
        return await handler(update, context)

    return wrapper
