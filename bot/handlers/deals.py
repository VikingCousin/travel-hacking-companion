import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from bot.deals.matcher import CATEGORY_EMOJI, CATEGORY_LABEL
from bot.deals.service import mark_deals_notified, refresh_all_sources, relevant_deals_for_user
from bot.validation import is_safe_url
from bot.whitelist import restricted

PAGE_SIZE = 5

NO_DEALS_TEXT = (
    "🔥 *Für dich*\n\n"
    "Aktuell habe ich keine passenden neuen Aktionen für dein Profil gefunden."
)
FOOTER = (
    "\nℹ️ Alle Aktionen stammen aus öffentlich zugänglichen Quellen – keine "
    "persönlichen Coupons oder Kontodaten. Prüfe Bedingungen und Laufzeit "
    "direkt beim Anbieter."
)


def _reason(deal: dict) -> str:
    parts = []
    if deal["matched_programs"]:
        parts.append(f"Du nutzt {', '.join(deal['matched_programs'])}.")
    if deal["matched_preferences"]:
        parts.append(f"Passt zu {', '.join(deal['matched_preferences'])}.")
    return " ".join(parts)


def _format_deals(deals: list[dict], offset: int) -> str:
    lines = ["🔥 *Für dich*", ""]
    if offset == 0:
        lines.append("Neu gefunden:")
        lines.append("")
    for i, deal in enumerate(deals, start=offset + 1):
        category = deal.get("category") or "travel"
        emoji = CATEGORY_EMOJI.get(category, "🌍")
        header = deal.get("loyalty_program") or deal.get("merchant") or CATEGORY_LABEL.get(category, "Reisen")
        title = escape_markdown(deal["title"], version=1)
        lines.append(f"{i}. {emoji} *{header}*")
        lines.append(title)
        reason = _reason(deal)
        if reason:
            lines.append(f"Warum relevant: {reason}")
        lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines)


def _keyboard(deals: list[dict], offset: int) -> InlineKeyboardMarkup:
    # url comes from a third-party RSS <link> - never trust its scheme
    # without checking (Phase 7L); a deal that somehow lacks a safe URL just
    # gets no button rather than a rejected/malformed one.
    rows = [
        [InlineKeyboardButton(f"🔗 {i}. Ansehen", url=deal["url"])]
        for i, deal in enumerate(deals, start=offset + 1)
        if is_safe_url(deal["url"])
    ]
    action_row = [InlineKeyboardButton("🔄 Aktualisieren", callback_data="deals:refresh")]
    if len(deals) >= PAGE_SIZE:
        # There *might* be more - we don't know without querying again, and a
        # harmless extra click that lands on "keine weiteren" is simpler and
        # safer than pre-counting the full pool on every render.
        action_row.append(InlineKeyboardButton("📚 Mehr", callback_data=f"deals:more:{offset + PAGE_SIZE}"))
    rows.append(action_row)
    rows.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


async def _render(update: Update, user_id: int, offset: int = 0) -> None:
    deals = relevant_deals_for_user(user_id, limit=PAGE_SIZE, offset=offset)

    if not deals:
        text = NO_DEALS_TEXT if offset == 0 else "📚 Keine weiteren passenden Aktionen gefunden."
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄 Aktualisieren", callback_data="deals:refresh")],
                [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")],
            ]
        )
    else:
        mark_deals_notified(user_id, [d["id"] for d in deals])
        text = _format_deals(deals, offset)
        keyboard = _keyboard(deals, offset)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )
    else:
        await update.effective_message.reply_text(
            text, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )


@restricted
async def deals_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
    await _render(update, update.effective_user.id)


@restricted
async def deals_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer("Aktualisiere...")
    # Blocking network I/O - run off the event loop so it can't stall other
    # users' updates while these 3 feeds are fetched.
    await asyncio.to_thread(refresh_all_sources)
    await _render(update, update.effective_user.id)


@restricted
async def deals_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    offset = int(query.data.split(":", 2)[2])
    await _render(update, update.effective_user.id, offset=offset)
