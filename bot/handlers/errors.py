import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

FRIENDLY_ERROR_TEXT = "Das hat gerade nicht funktioniert. Bitte versuche es noch einmal."


def _is_harmless_not_modified(error: BaseException) -> bool:
    """Telegram raises BadRequest("Message is not modified: ...") whenever an
    edit_message_text call would produce content identical to what's already
    shown - e.g. a user re-tapping "🔄 Aktualisieren" when nothing new was
    found, or "🏠 Hauptmenü" when already on that screen. Nothing is actually
    broken (the screen already shows the correct content), so this must not
    surface as "Das hat gerade nicht funktioniert" - identified as the root
    cause of that message appearing in Phase 7 manual testing (Phase 7B, see
    docs/PHASE7_REPORT.md)."""
    return isinstance(error, BadRequest) and "message is not modified" in str(error).lower()


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global PTB error handler: logs the full exception (never any secret -
    httpx/token logging is already suppressed in main.py) and, if a chat can
    be identified, replies with a friendly message instead of leaving the
    user without any response or exposing a traceback. One specific,
    harmless BadRequest (see _is_harmless_not_modified) is deliberately not
    surfaced to the user - everything else still is."""
    if _is_harmless_not_modified(context.error):
        logger.debug("Ignored harmless 'message is not modified' edit (user re-tapped an unchanged view)")
        return

    chat_id = None
    callback_data = None
    if isinstance(update, Update):
        chat = update.effective_chat
        chat_id = chat.id if chat else None
        if update.callback_query:
            callback_data = update.callback_query.data

    logger.error(
        "Unhandled exception while processing an update (chat_id=%s, callback_data=%s)",
        chat_id,
        callback_data,
        exc_info=context.error,
    )

    if chat_id is None:
        return

    try:
        await context.bot.send_message(chat_id=chat_id, text=FRIENDLY_ERROR_TEXT)
    except Exception:
        logger.exception("Failed to send the friendly error message to chat %s", chat_id)
