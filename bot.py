import os
import io
import logging
import time
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

import database as db
import llm_helper

# --- Rate Limiting ---
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGE_LENGTH = 500
_user_message_timestamps = defaultdict(list)

# Whitelist of valid callback data values
VALID_CALLBACKS = {'last_expenses', 'monthly_list', 'pie_chart', 'insights'}

# ── Emoji Display Mapping ──
# The data layer stores clean strings ('Food', 'Transport').
# This mapping adds emojis for the Telegram UI only.
CATEGORY_EMOJI = {
    'Housing': '🏠', 'Food': '🍔', 'Transport': '🚗',
    'Entertainment': '🎉', 'Shopping': '🛍️', 'Health': '❤️',
    'Education': '📚', 'Financial': '💸', 'Other': '❓',
}


def _display_category(category: str) -> str:
    """Convert a clean category string to an emoji-decorated display string."""
    # If it already has an emoji (legacy data), pass through as-is
    if any(ord(c) > 0xFFFF for c in category):
        return category
    emoji = CATEGORY_EMOJI.get(category, '❓')
    return f"{emoji} {category}"


def _is_rate_limited(user_id: int) -> bool:
    """Check if a user has exceeded the rate limit."""
    now = time.time()
    window = 60  # 1 minute window

    # Clean old timestamps
    _user_message_timestamps[user_id] = [
        ts for ts in _user_message_timestamps[user_id] if now - ts < window
    ]

    if len(_user_message_timestamps[user_id]) >= MAX_MESSAGES_PER_MINUTE:
        return True

    _user_message_timestamps[user_id].append(now)
    return False


def _cleanup_rate_limit_data():
    """Periodically clean up stale rate limit entries to prevent memory leak."""
    now = time.time()
    stale_users = [
        uid for uid, timestamps in _user_message_timestamps.items()
        if not timestamps or (now - max(timestamps)) > 300  # 5 min stale
    ]
    for uid in stale_users:
        del _user_message_timestamps[uid]


def _escape_markdown(text: str) -> str:
    """
    Escape special Markdown characters in user-supplied text
    to prevent Telegram Markdown injection.
    """
    if not text:
        return ""
    # Escape characters that have meaning in Telegram Markdown V1
    for char in ['*', '_', '`', '[']:
        text = text.replace(char, f'\\{char}')
    return text


def _private_only(func):
    """Decorator: only respond in private chats."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type != 'private':
            return
        return await func(update, context)
    return wrapper


# ── Command Handlers ──

@_private_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="👋 *Welcome to FinTechBot!* 🤖💰\n\nI can help you track your expenses and save money.\n\n📝 *Try it:* Send me an expense like:\n*\"Spent 50 shekels on pizza\"*\n*\"Taxi to work 40\"*\n\nThen use /menu to see your stats! 📊\nType /help for all commands.",
        parse_mode='Markdown'
    )


@_private_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command."""
    text = (
        "📖 *FinTechBot Commands:*\n\n"
        "📝 *Track expenses* — just type naturally:\n"
        "  _\"Spent 50 on pizza\"_\n"
        "  _\"שילמתי 200 שקל על סופר\"_\n\n"
        "📊 /menu — Dashboard & insights\n"
        "💰 /budget `amount` — Set monthly budget\n"
        "↩️ /undo — Remove last expense\n"
        "📤 /export — Download CSV file\n"
        "🗑️ /deleteall — Clear all your data\n"
        "❓ /help — This message"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')


@_private_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the interactive menu."""
    keyboard = [
        [InlineKeyboardButton("📜 Last Expenses", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly List", callback_data='monthly_list')],
        [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart')],
        [InlineKeyboardButton("💡 AI Insights", callback_data='insights')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('📊 *My Finances Menu:*', reply_markup=reply_markup, parse_mode='Markdown')


@_private_only
async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the most recent expense."""
    user_id = update.effective_user.id
    last_id = db.get_last_expense_id(user_id)

    if not last_id:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="📭 No expenses to undo.")
        return

    success = db.delete_expense(user_id, last_id)
    if success:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="↩️ *Last expense removed!*", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Could not undo. Try again.")


@_private_only
async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets or shows the monthly budget."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Check if user provided an amount
    if context.args:
        try:
            amount = float(context.args[0])
            db.set_budget(user_id, amount)
            await context.bot.send_message(chat_id=chat_id, text=f"💰 *Monthly budget set to {amount:.0f}!*", parse_mode='Markdown')
        except ValueError as e:
            await context.bot.send_message(chat_id=chat_id, text=f"⚠️ {str(e)}")
        except (IndexError):
            await context.bot.send_message(chat_id=chat_id, text="⚠️ Usage: /budget `5000`", parse_mode='Markdown')
    else:
        budget = db.get_budget(user_id)
        if budget:
            total = db.get_monthly_summary(user_id)
            remaining = budget - total
            status = "✅" if remaining > 0 else "🚨"
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"💰 *Budget: {budget:.0f}*\n📊 Spent: {total:.0f}\n{status} Remaining: {remaining:.0f}",
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text="💰 No budget set.\nUse /budget `5000` to set one.", parse_mode='Markdown')


@_private_only
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports all expenses as a CSV file."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    csv_data = db.export_expenses_csv(user_id)
    if not csv_data or csv_data.strip() == 'Date,Amount,Category,Description':
        await context.bot.send_message(chat_id=chat_id, text="📭 No expenses to export.")
        return

    file = io.BytesIO(csv_data.encode('utf-8'))
    file.name = "expenses.csv"
    await context.bot.send_document(chat_id=chat_id, document=file, caption="📤 *Your expenses export*", parse_mode='Markdown')


@_private_only
async def deleteall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks for confirmation before deleting all expenses."""
    keyboard = [
        [InlineKeyboardButton("🗑️ Yes, delete everything", callback_data='confirm_delete_all')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_delete_all')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚠️ *Are you sure you want to delete ALL your expenses?*\n\nThis action *cannot be undone!*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


@_private_only
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets or shows the user's age and wage."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if context.args and len(context.args) == 2:
        try:
            age = int(context.args[0])
            wage = float(context.args[1])
            db.set_profile(user_id, age, wage)
            await context.bot.send_message(chat_id=chat_id, text=f"👤 *Profile Updated!*\nAge: {age}\nWage: {wage:.0f} NIS", parse_mode='Markdown')
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text="⚠️ Usage: /profile `<age> <wage>`\nExample: `/profile 25 12000`", parse_mode='Markdown')
    else:
        profile = db.get_profile(user_id)
        if profile:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"👤 *Your Profile:*\nAge: {profile['age']}\nWage: {profile['wage']:.0f} NIS\n\nTo update: `/profile <age> <wage>`",
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text="👤 No profile set.\nUse `/profile <age> <wage>` to get better AI insights.", parse_mode='Markdown')



# ── Callback Handler ──

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data

    # Handle "delete all" confirmation
    if data == 'confirm_delete_all':
        count = db.delete_all_expenses(telegram_id)
        await query.edit_message_text(text=f"🗑️ *Done!* Deleted {count} expense(s).\n\nYou're starting fresh.", parse_mode='Markdown')
        return
    if data == 'cancel_delete_all':
        await query.edit_message_text(text="✅ Cancelled. Your expenses are safe.")
        return

    # Handle single delete callbacks (format: "del_123")
    if data.startswith("del_"):
        try:
            expense_id = int(data[4:])
            success = db.delete_expense(telegram_id, expense_id)
            if success:
                await query.edit_message_text(text="🗑️ *Expense deleted!*\n\nUse /menu to refresh.", parse_mode='Markdown')
            else:
                await query.edit_message_text(text="⚠️ Could not delete. It may already be removed.")
        except (ValueError, Exception):
            await query.edit_message_text(text="⚠️ Error deleting expense.")
        return

    # Validate other callback data against whitelist
    if data not in VALID_CALLBACKS:
        logger.warning(f"Invalid callback data from user {telegram_id}: rejected")
        return

    try:
        if data == 'last_expenses':
            expenses = db.get_recent_expenses(user_id=telegram_id, limit=5)
            if not expenses:
                text = "📭 No expenses found yet."
                await query.edit_message_text(text=text)
            else:
                text = "📜 *Last 5 Expenses:*\n\n"
                buttons = []
                for exp in expenses:
                    date_short = exp[1][5:10]
                    safe_desc = _escape_markdown(exp[4] or '')
                    text += f"🗓️ `{date_short}` | 💰 *{exp[2]}* | {_display_category(exp[3])}\n_{safe_desc}_\n\n"
                    buttons.append([InlineKeyboardButton(f"🗑️ Delete {exp[2]} {_display_category(exp[3])}", callback_data=f"del_{exp[0]}")])
                reply_markup = InlineKeyboardMarkup(buttons)
                await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

        elif data == 'monthly_list':
            expenses = db.get_monthly_expenses(user_id=telegram_id)
            if not expenses:
                text = "📅 No expenses this month."
            else:
                total = sum(e[2] for e in expenses)
                text = f"📅 *This Month's Activity*\n🏆 *Total: {total:.2f}*\n\n"
                for exp in expenses:
                    date_short = exp[1][5:10]
                    text += f"• `{date_short}`: *{exp[2]}* - {_display_category(exp[3])}\n"
            await query.edit_message_text(text=text, parse_mode='Markdown')

        elif data == 'pie_chart':
            totals = db.get_category_totals(user_id=telegram_id)
            if not totals:
                await query.edit_message_text(text="📉 No data for a chart yet.")
                return

            total_sum = sum(totals.values())
            if total_sum <= 0:
                await query.edit_message_text(text="📉 No valid data for a chart.")
                return

            text = f"📊 *Monthly Breakdown* (Total: {total_sum:.2f})\n\n"
            sorted_totals = sorted(totals.items(), key=lambda x: x[1], reverse=True)
            for cat, amount in sorted_totals:
                percent = (amount / total_sum) * 100
                bar_len = int(percent / 10) + 1
                bar = "🟦" * bar_len
                text += f"{_display_category(cat)}: *{amount:.1f}* ({percent:.0f}%)\n{bar}\n"
            await query.edit_message_text(text=text, parse_mode='Markdown')

        elif data == 'insights':
            await query.edit_message_text(text="🤔 *Analyzing your spending...*\n_(This might take a few seconds)_", parse_mode='Markdown')
            
            # Gather all context for smarter insights
            totals = db.get_category_totals(user_id=telegram_id)
            if not totals or sum(totals.values()) <= 0:
                await query.edit_message_text(text="❌ Not enough data for insights yet. Try adding some expenses first!")
                return

            budget = db.get_budget(telegram_id)
            recent = db.get_recent_expenses(user_id=telegram_id, limit=10)
            profile = db.get_profile(telegram_id)
            
            # Call enhanced insights
            insight = llm_helper.generate_insights(
                totals=totals,
                age=profile['age'] if profile else None,
                wage=profile['wage'] if profile else None,
                budget=budget,
                recent_expenses=recent
            )

            # Format for better readability
            safe_insight = _escape_markdown(insight)
            await query.edit_message_text(text=f"💡 *FinTechBot Insights:*\n\n{safe_insight}", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in button_handler for user {telegram_id}: {type(e).__name__}")
        try:
            await query.edit_message_text(text="⚠️ Something went wrong. Please try again.")
        except Exception:
            pass


# ── Message Handler ──

@_private_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for text messages. Uses LLM to parse and saves to DB."""
    user_text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Rate limiting check
    if _is_rate_limited(user_id):
        await context.bot.send_message(chat_id=chat_id, text="⏳ You're sending messages too fast. Please wait a moment.")
        return

    # Periodic cleanup of stale rate limit data
    _cleanup_rate_limit_data()

    # Input length check
    if not user_text or len(user_text) > MAX_MESSAGE_LENGTH:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Message too long. Please keep it under {MAX_MESSAGE_LENGTH} characters.")
        return

    processing_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ _Processing..._", parse_mode='Markdown')

    try:
        # 1. Parse with LLM
        expense_data = llm_helper.parse_expense(user_text)

        if expense_data:
            amount = expense_data.get('amount')
            category = expense_data.get('category')
            description = expense_data.get('description', '')

            # 2. Save to Database
            if amount and category:
                db.add_expense(user_id, amount, category, description)

                # Escape description for safe Markdown display
                safe_desc = _escape_markdown(description)
                response_text = (
                    f"✅ *Expense Saved!*\n\n"
                    f"💰 Amount: *{amount}*\n"
                    f"📂 Category: {_display_category(category)}\n"
                    f"📝 Details: _{safe_desc}_\n\n"
                    f"Use /menu to see your dashboard."
                )

                # Budget check
                budget = db.get_budget(user_id)
                if budget:
                    total = db.get_monthly_summary(user_id)
                    if total > budget:
                        response_text += f"\n\n🚨 *Budget alert!* You've spent {total:.0f}/{budget:.0f}"
                    elif total > budget * 0.8:
                        response_text += f"\n\n⚠️ *Heads up:* {total:.0f}/{budget:.0f} spent (80%+ of budget)"
            else:
                response_text = "⚠️ *Error*: Could not extract amount or category."
        else:
            response_text = "❓ I didn't understand that as an expense.\nTry: *\"Spent 50 on food\"*"

    except ValueError as e:
        logger.warning(f"Validation error for user {user_id}: {e}")
        response_text = "⚠️ Invalid expense data. Please check the amount and try again."
    except Exception as e:
        logger.error(f"Unexpected error for user {user_id}: {type(e).__name__}")
        response_text = "⚠️ Something went wrong. Please try again later."

    # Delete processing message and send result
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
    except Exception:
        pass
    await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode='Markdown')


if __name__ == '__main__':
    # Initialize DB at startup
    db.init_db()

    # Retrieve the token from environment variables
    token = os.getenv('TELEGRAM_BOT_TOKEN')

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in .env file.")
        exit(1)

    # Build the application
    application = ApplicationBuilder().token(token).build()

    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('menu', menu_command))
    application.add_handler(CommandHandler('undo', undo_command))
    application.add_handler(CommandHandler('budget', budget_command))
    application.add_handler(CommandHandler('export', export_command))
    application.add_handler(CommandHandler('deleteall', deleteall_command))
    application.add_handler(CommandHandler('profile', profile_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Run the bot
    logger.info("Bot is starting...")
    application.run_polling()

