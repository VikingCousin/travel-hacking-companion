"""🔎 Einkauf optimieren (Phase 7.5). Distinct from /deals: the user has a
concrete purchase in mind and wants "where do I start this purchase to
collect the most rewards", not a proactive news feed. Free-text category
input is scoped to this ConversationHandler ONLY (states AWAIT_CATEGORY /
AWAIT_AMOUNT) - it can never intercept a message meant for /punkte, /ziele,
the profile flows, or anything else, because PTB only routes a text message
to this handler while this specific conversation is actively tracked for
that user (see bot/main.py's handler-order comments for the general
pattern).
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

from bot.menu import MENU_INTRO_TEXT, build_main_menu
from bot.shopping.categories import CATEGORY_LABELS, match_category
from bot.shopping.service import estimate_reward, find_shopping_options
from bot.validation import is_safe_url
from bot.whitelist import restricted

AWAIT_CATEGORY, AWAIT_AMOUNT = range(2)

ENTRY_TEXT = (
    "🔎 *Einkauf optimieren*\n\n"
    "Was möchtest du kaufen?\n\n"
    "Du kannst z. B. schreiben:\n"
    "• Schuhe\n• Bekleidung\n• Elektronik\n• Drogerie\n• Reisen"
)
# Only "❌ Abbrechen" here - shown while AWAIT_CATEGORY is an active,
# tracked conversation state. A "menu:home"-style button here would fall
# through to the generic menu_callback without ever returning
# ConversationHandler.END, leaving the conversation stuck tracked in this
# state - the next "menu:shopping" tap would then skip entry_points
# entirely (PTB only checks entry_points when nothing is tracked) and
# eventually reach menu_callback's coming_soon_text('shopping') -> KeyError.
# "❌ Abbrechen" already ends the conversation cleanly and its own
# confirmation screen offers a Hauptmenü button afterwards - consistent
# with every other ConversationHandler in this project (/punkte, /ziele,
# custom program, preferences), none of which embed a menu:* button in a
# live state.
CANCEL_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("❌ Abbrechen", callback_data="shop_cancel")],
    ]
)


def _clear_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ("shop_category", "shop_category_label"):
        context.user_data.pop(key, None)


async def _send_or_edit(update: Update, text: str, keyboard: InlineKeyboardMarkup, parse_mode="Markdown") -> None:
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, parse_mode=parse_mode, reply_markup=keyboard)


@restricted
async def shopping_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
    _clear_state(context)
    await _send_or_edit(update, ENTRY_TEXT, CANCEL_KEYBOARD)
    return AWAIT_CATEGORY


@restricted
async def shopping_receive_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.effective_message.text.strip()
    category = match_category(text)
    if category is None:
        await update.effective_message.reply_text(
            "🤔 Diese Kategorie kenne ich noch nicht. Versuch es z. B. mit \"Schuhe\", "
            "\"Elektronik\", \"Drogerie\" oder \"Reisen\".",
            reply_markup=CANCEL_KEYBOARD,
        )
        return AWAIT_CATEGORY

    context.user_data["shop_category"] = category
    context.user_data["shop_category_label"] = CATEGORY_LABELS[category]

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💶 Betrag angeben", callback_data="shop_amount_yes")],
            [InlineKeyboardButton("➡️ Ohne Betrag", callback_data="shop_amount_no")],
            [InlineKeyboardButton("❌ Abbrechen", callback_data="shop_cancel")],
        ]
    )
    await update.effective_message.reply_text(
        f"{CATEGORY_LABELS[category]}\n\nMöchtest du einen ungefähren Kaufbetrag angeben? "
        "(für eine Meilen-/Punkte-Schätzung)",
        reply_markup=keyboard,
    )
    return AWAIT_AMOUNT


@restricted
async def shopping_amount_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Wie viel möchtest du ungefähr ausgeben? (z. B. 200 oder 49,90)")
    return AWAIT_AMOUNT


def _parse_eur_amount(text: str) -> float | None:
    cleaned = text.strip().replace("€", "").replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


@restricted
async def shopping_receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_eur_amount(update.effective_message.text)
    if amount is None:
        await update.effective_message.reply_text(
            "❌ Das habe ich nicht als Betrag verstanden. Bitte gib eine positive Zahl ein (z. B. 200 oder 49,90)."
        )
        return AWAIT_AMOUNT
    return await _show_results(update, context, amount)


@restricted
async def shopping_no_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _show_results(update, context, None)


def _format_offer(offer: dict, amount: float | None) -> list[str]:
    lines = [f"{offer['program_emoji'] or '🔸'} *{offer['program_name']}* · {offer['merchant']}"]
    if offer["reward_rate"] is not None:
        rate_line = f"{offer['reward_rate']:g} {offer['reward_unit']} / €"
        if offer["is_promotion"]:
            rate_line += " 🔥"
        lines.append(rate_line)
        if amount is not None:
            estimate = estimate_reward(offer, amount)
            lines.append(f"≈ {estimate:g} {offer['reward_unit']} bei {amount:g} €")
    elif offer["promotion_text"]:
        lines.append(escape_markdown(offer["promotion_text"], version=1))
    else:
        lines.append("Aktuelle Reward-Rate konnte nicht zuverlässig bestimmt werden.")
    return lines


def _results_keyboard(offers: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, offer in enumerate(offers, start=1):
        url = offer.get("landing_url") or offer.get("source_url")
        if is_safe_url(url):
            rows.append([InlineKeyboardButton(f"🔗 {i}. {offer['merchant'][:20]} starten", url=url)])
    rows.append([InlineKeyboardButton("💳 Passende Karte", callback_data="shop_karte")])
    rows.append([InlineKeyboardButton("🔎 Neue Suche", callback_data="shop_new")])
    rows.append([InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


async def _show_results(update: Update, context: ContextTypes.DEFAULT_TYPE, amount: float | None) -> int:
    category = context.user_data.get("shop_category")
    category_label = context.user_data.get("shop_category_label", "")
    user_id = update.effective_user.id

    offers = find_shopping_options(user_id, category) if category else []

    if not offers:
        text = (
            f"🤔 *Keine passende Rewards-Option gefunden*\n\n"
            f"Für {category_label} konnte ich mit deinen hinterlegten Programmen aktuell "
            "keine verifizierte Shopping-Option finden."
        )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔎 Neue Suche", callback_data="shop_new")],
                [InlineKeyboardButton("👤 Programme prüfen", callback_data="menu:profil")],
                [InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")],
            ]
        )
    else:
        lines = [f"🔎 *Beste Optionen für {category_label}*", ""]
        medals = ["🥇", "🥈", "🥉"]
        for i, offer in enumerate(offers):
            medal = medals[i] if i < len(medals) else "▫️"
            lines.append(medal + " " + "\n".join(_format_offer(offer, amount)))
            lines.append("")
        lines.append(
            "💡 Portal-Rewards und Kartenzahlung werden nicht automatisch addiert - prüfe vor dem Kauf, "
            "ob Aktionen kombinierbar sind."
        )
        text = "\n".join(lines)
        keyboard = _results_keyboard(offers)

    # Text-input path (amount typed) has no message to edit -> new message.
    # Callback path ("➡️ Ohne Betrag") edits the existing one in place,
    # consistent with the rest of the project's Phase 7C navigation pattern.
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )
    else:
        await update.effective_message.reply_text(
            text, parse_mode="Markdown", reply_markup=keyboard, disable_web_page_preview=True
        )
    _clear_state(context)
    return ConversationHandler.END


@restricted
async def shopping_to_karte(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """[💳 Passende Karte]: hands off to the existing Phase-3 recommender
    (its own engine, restricted to the user's own cards) for a generic
    online-purchase situation - never invents or combines a "stacked" value
    with the shopping-portal reward shown above. Calls payment.py's internal
    render function directly rather than routing through a callback_data
    string - telegram.CallbackQuery is immutable, it can't be faked by
    editing query.data on the object we already have."""
    from bot.handlers.payment import _show_recommendation

    query = update.callback_query
    await query.answer()
    await _show_recommendation(
        update, update.effective_user.id, "shopping", "online", "🛍 Shopping", "Online"
    )


@restricted
async def shopping_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_state(context)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Hauptmenü", callback_data="menu:home")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Abgebrochen.", reply_markup=keyboard)
    else:
        await update.effective_message.reply_text("Abgebrochen.", reply_markup=keyboard)
    return ConversationHandler.END


@restricted
async def shopping_menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback for a stray "menu:home" reaching a still-tracked shopping
    conversation state. Returning ConversationHandler.END here is not
    enough on its own to show the Hauptmenü - within a PTB handler group,
    once one handler has processed an update no other handler gets a turn
    at the same update, so the generic menu_callback would never run for
    this tap. This fallback therefore ends the conversation AND renders the
    Hauptmenü itself, so the *next* menu:shopping tap correctly hits
    entry_points again instead of silently reaching menu_callback's
    coming_soon_text('shopping') -> KeyError (the reported bug)."""
    _clear_state(context)
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(MENU_INTRO_TEXT, reply_markup=build_main_menu())
    return ConversationHandler.END


shopping_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("shopping", shopping_entry),
        CallbackQueryHandler(shopping_entry, pattern=r"^menu:shopping$"),
        CallbackQueryHandler(shopping_entry, pattern=r"^shop_new$"),
    ],
    states={
        AWAIT_CATEGORY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, shopping_receive_category),
        ],
        AWAIT_AMOUNT: [
            CallbackQueryHandler(shopping_amount_prompt, pattern=r"^shop_amount_yes$"),
            CallbackQueryHandler(shopping_no_amount, pattern=r"^shop_amount_no$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, shopping_receive_amount),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(shopping_cancel, pattern=r"^shop_cancel$"),
        CommandHandler("abbrechen", shopping_cancel),
        # Defense in depth: even without a visible menu:home button in any
        # live state (see CANCEL_KEYBOARD above), a stray one reaching a
        # tracked state (e.g. from an older message) must still end the
        # conversation cleanly rather than leave it stuck - see
        # shopping_menu_fallback's docstring for the exact failure mode this
        # prevents.
        CallbackQueryHandler(shopping_menu_fallback, pattern=r"^menu:home$"),
    ],
    conversation_timeout=600,
)
