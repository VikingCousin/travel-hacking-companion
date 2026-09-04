"""Shared mock-Update builders for the offline handler tests. Not pytest
fixtures on purpose - the project has no test-framework dependency, these
scripts run with plain `python tests/test_*.py` (see tests/README.md)."""

from unittest.mock import AsyncMock, MagicMock


def make_user(uid: int):
    user = MagicMock()
    user.id = uid
    user.first_name = f"User{uid}"
    user.username = f"user{uid}"
    return user


def make_message_update(uid: int, text: str):
    user = make_user(uid)
    message = MagicMock()
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock()
    update.effective_user = user
    update.effective_message = message
    update.callback_query = None
    return update, message


def make_callback_update(uid: int, data: str):
    user = make_user(uid)
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    message = MagicMock()
    query.message = message
    update = MagicMock()
    update.effective_user = user
    update.callback_query = query
    update.effective_message = message
    return update, query, message


class Ctx:
    """Minimal stand-in for telegram.ext.ContextTypes.DEFAULT_TYPE - handlers
    here only ever touch .user_data."""

    def __init__(self):
        self.user_data = {}
