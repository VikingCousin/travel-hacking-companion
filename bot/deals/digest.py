"""Daily personalized digest: once a day, sends each registered user a
compact summary of NEW relevant deals since their last digest/view - dedup
is shared with /deals via user_deal_notifications, so a deal already seen
(either through /deals or a previous digest) is never sent again, and never
to the wrong user. Sends NOTHING if a user has no new relevant deals - no
"nothing today" message, to avoid spamming an inactive user daily.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.helpers import escape_markdown

from bot.deals.matcher import CATEGORY_EMOJI, CATEGORY_LABEL
from bot.deals.service import all_user_ids, find_new_relevant_deals_for_alerting, mark_deals_notified
from bot.validation import is_safe_url

logger = logging.getLogger(__name__)

DIGEST_LIMIT = 5


def _format_digest(deals: list[dict]) -> str:
    lines = ["🔥 *Deine heutigen Aktionen*", ""]
    for deal in deals:
        category = deal.get("category") or "travel"
        emoji = CATEGORY_EMOJI.get(category, "🌍")
        header = deal.get("loyalty_program") or deal.get("merchant") or CATEGORY_LABEL.get(category, "Reisen")
        title = escape_markdown(deal["title"], version=1)
        lines.append(f"{emoji} *{header}*")
        lines.append(title)
        lines.append("")
    lines.append(f"{len(deals)} neue relevante Aktion(en) seit deinem letzten Digest.")
    return "\n".join(lines)


def _keyboard(deals: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"🔗 {i}. Ansehen", url=d["url"])]
        for i, d in enumerate(deals, start=1)
        if is_safe_url(d["url"])
    ]
    rows.append([InlineKeyboardButton("🔥 Alle Deals", callback_data="menu:deals")])
    return InlineKeyboardMarkup(rows)


async def send_daily_digest_for_user(bot, user_id: int) -> bool:
    """Sends the digest to one user if they have new relevant deals. Returns
    True if a message was actually sent, False if there was nothing new
    (correctly silent - not a failure). Split out from the job loop below so
    a later per-user-scheduled digest time can call this directly without
    restructuring anything (see docs/PHASE7_REPORT.md)."""
    deals = find_new_relevant_deals_for_alerting(user_id, limit=DIGEST_LIMIT)
    if not deals:
        return False

    text = _format_digest(deals)
    keyboard = _keyboard(deals)
    try:
        await bot.send_message(
            chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )
    except TelegramError:
        logger.exception("Failed to send daily digest to user %s", user_id)
        return False

    mark_deals_notified(user_id, [d["id"] for d in deals])
    return True


async def send_daily_digest_job(context) -> None:
    """PTB JobQueue callback, registered once for all users at a single
    global time (see bot/main.py). Iterates every registered user; each
    user's own program/preference profile decides what (if anything) they
    receive - see send_daily_digest_for_user."""
    sent_count = 0
    for user_id in all_user_ids():
        if await send_daily_digest_for_user(context.bot, user_id):
            sent_count += 1
    if sent_count:
        logger.info("Daily digest: sent to %d user(s)", sent_count)
