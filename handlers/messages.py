import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import services.database as db
import services.firestore_service as firestore_service
import services.llm_helper as llm_helper
from handlers.utils import (
    _display_category, _escape_markdown, _safe_send,
    _get_category_keyboard, _is_rate_limited, _cleanup_rate_limit_data, _private_only
)
from handlers.settings_ui import _handle_setting_input
from core.config import logger, MAX_MESSAGE_LENGTH
from datetime import datetime


@_private_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for text messages. Uses LLM to parse and saves to DB."""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Priority: check for a pending settings input before doing expense parsing
    awaiting = context.user_data.get('awaiting_setting')
    if awaiting:
        await _handle_setting_input(update, context, awaiting)
        return

    # Rate limiting check
    if _is_rate_limited(user_id):
        await _safe_send(context.bot, chat_id, "⏳ You're sending messages too fast. Please wait a moment.")
        return

    _cleanup_rate_limit_data()

    # Input length checks
    if len(user_text.strip()) == 0:
        return
    if len(user_text) > MAX_MESSAGE_LENGTH:
        await _safe_send(context.bot, chat_id, f"⚠️ Message too long. Please keep it under {MAX_MESSAGE_LENGTH} characters.")
        return

    processing_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ _Processing..._", parse_mode='Markdown')

    # These must be defined at this scope so the finally/send block can read them
    response_text = "⚠️ Something went wrong. Please try again later."
    reply_markup = None

    try:
        expense_data = await asyncio.to_thread(llm_helper.parse_expense, user_text)
        status = expense_data.get('status', 'not_expense') if expense_data else 'not_expense'

        if status == 'success':
            amount = expense_data.get('amount')
            category = expense_data.get('category')
            description = expense_data.get('description', '')

            if amount and category:
                await firestore_service.add_expense(user_id, amount, category, description)

                safe_desc = _escape_markdown(description)
                is_income = expense_data.get('type') == 'income'
                type_icon = "🟢" if is_income else "🔴"
                word = "Income" if is_income else "Expense"

                response_text = (
                    f"✅ *{word} Saved!*\n\n"
                    f"💰 Amount: {type_icon} *₪{amount:.2f}*\n"
                    f"📂 Category: {_display_category(category)}\n"
                    f"📝 Details: _{safe_desc}_\n"
                )

                # ── Currency Conversion Notice ──
                if expense_data.get('converted'):
                    orig_amount = expense_data.get('original_amount', amount)
                    orig_currency = expense_data.get('original_currency', 'NIS')
                    symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥'}
                    symbol = symbols.get(orig_currency, orig_currency)
                    response_text += f"\n💱 Converted from *{symbol}{orig_amount:.2f}* → *₪{amount:.2f}*\n"

                response_text += "\nUse /menu to see your dashboard."

                # ── Budget / Goal Smart Notification ──
                if is_income:
                    profile = await firestore_service.get_profile(user_id)
                    goal = profile.get('additional_info') if profile else None
                    if goal:
                        response_text += f"\n🎯 *Progress!* You're one step closer to: _{_escape_markdown(goal)}_"
                else:
                    budget = await firestore_service.get_budget(user_id)
                    if budget and budget > 0:
                        spent_this_month, _ = await firestore_service.get_monthly_summary(user_id)
                        pct = (spent_this_month / budget) * 100
                        bar_len = 10
                        filled = min(bar_len, int((pct / 100) * bar_len))
                        bar = "▮" * filled + "▯" * (bar_len - filled)
                        response_text += f"\n📊 *Budget:* [{bar}] {pct:.0f}%\n"
                        if pct >= 100:
                            response_text += "🚨 *Warning: You have exceeded your monthly budget!*"
                        elif pct >= 80:
                            response_text += "⚠️ *Careful: You have used over 80% of your budget.*"

                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Undo", callback_data='undo_last'),
                     InlineKeyboardButton("📊 Dashboard", callback_data='back_to_menu')]
                ])
            else:
                response_text = "⚠️ *Error*: Could not extract amount or category."

        elif status == 'no_category':
            amt = expense_data.get('amount') if expense_data else None
            desc = (expense_data.get('text', user_text) if expense_data else user_text)

            if amt:
                context.user_data['pending_expense'] = {"amount": float(amt), "description": desc}
                response_text = f"🔢 Got *₪{amt:.2f}*.\n\nPlease pick a category for _{_escape_markdown(desc)}_:"
                reply_markup = _get_category_keyboard()
            else:
                response_text = "🔢 I see a number but couldn't figure out the category.\nTry: *\"Spent 50 on food\"*"

        else:
            # not_expense — friendly guidance
            response_text = (
                "👋 Hey! I'm your expense tracker bot.\n"
                "Send me what you spent, like:\n"
                "• *\"Spent 50 on food\"*\n"
                "• *\"taxi 35\"*\n"
                "• *\"קניתי פיצה ב-30\"*\n\n"
                "Or use /menu for your dashboard."
            )

    except ValueError as e:
        logger.warning(f"Validation error for user {user_id}: {e}")
        response_text = "⚠️ Invalid expense data. Please check the amount and try again."
    except Exception as e:
        logger.error(f"Unexpected error for user {user_id}: {type(e).__name__}: {e}")
        response_text = "⚠️ Something went wrong. Please try again later."

    # Delete the "Processing..." placeholder
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
    except Exception:
        pass

    await _safe_send(context.bot, chat_id, response_text, reply_markup=reply_markup)
