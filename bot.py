import os
import io
import asyncio
import logging
import time
import traceback
from datetime import datetime

from functools import wraps
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress httpx logs that leak the bot token in URLs
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Onboarding / Settings States ---
ASK_AGE, ASK_INCOME, ASK_CURRENCY, ASK_INFO = range(4)

import database as db
import llm_helper

# --- Constants ---
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGE_LENGTH = 500
TELEGRAM_MAX_LENGTH = 4096  # Telegram's hard limit for a single message
_user_message_timestamps = defaultdict(list)

# Single-tenant security: Load allowed user ID
ALLOWED_USER_ID = os.getenv('ALLOWED_USER_ID')
if ALLOWED_USER_ID:
    try:
        ALLOWED_USER_ID = int(ALLOWED_USER_ID)
    except ValueError:
        logger.error(f"Invalid ALLOWED_USER_ID in .env: {ALLOWED_USER_ID}. Must be an integer.")
        ALLOWED_USER_ID = None

# Whitelist of valid callback data values
VALID_CALLBACKS = {
    'last_expenses', 'monthly_list', 'this_month', 'year_overview', 'pie_chart', 
    'insights', 'delete_all_monthly', 'back_to_menu', 'settings_menu',
    'export_csv', 'delete_all', 'undo_last'
}

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


# ── Pie Chart Generator ──

# Category colors — vibrant, distinct, modern palette
CATEGORY_COLORS = {
    'Food':          '#FF6B6B',  # Coral red
    'Transport':     '#4ECDC4',  # Teal
    'Housing':       '#45B7D1',  # Sky blue
    'Entertainment': '#F7DC6F',  # Gold
    'Shopping':      '#BB8FCE',  # Lavender
    'Health':        '#58D68D',  # Green
    'Education':     '#5DADE2',  # Blue
    'Financial':     '#F0B27A',  # Peach
    'Other':         '#AEB6BF',  # Gray
}


def _generate_pie_chart(totals: dict, total_sum: float) -> io.BytesIO:
    """
    Generates a professional donut pie chart image and returns it as a BytesIO buffer.
    """
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend (no GUI needed)
    import matplotlib.pyplot as plt
    import numpy as np
    try:
        # Sort by amount descending
        sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
        labels = []
        sizes = []
        colors = []

        for cat, amount in sorted_items:
            percent = (amount / total_sum) * 100
            labels.append(f"{_display_category(cat)}\n₪{amount:,.0f} ({percent:.0f}%)")
            sizes.append(amount)
            colors.append(CATEGORY_COLORS.get(cat, '#AEB6BF'))

        # Create figure with dark background
        fig, ax = plt.subplots(figsize=(8, 8), facecolor='#1a1a2e')
        ax.set_facecolor('#1a1a2e')

        # Draw donut chart
        wedges, texts = ax.pie(
            sizes,
            colors=colors,
            startangle=90,
            pctdistance=0.80,
            wedgeprops=dict(width=0.45, edgecolor='#1a1a2e', linewidth=2.5),
        )

        # Add labels outside the chart
        for i, (wedge, label) in enumerate(zip(wedges, labels)):
            angle = (wedge.theta2 + wedge.theta1) / 2
            x = np.cos(np.radians(angle))
            y = np.sin(np.radians(angle))
            ha = 'left' if x > 0 else 'right'
            ax.annotate(
                label,
                xy=(x * 0.78, y * 0.78),
                xytext=(x * 1.35, y * 1.35),
                fontsize=11,
                fontweight='bold',
                color='white',
                ha=ha,
                va='center',
                arrowprops=dict(arrowstyle='-', color='#ffffff55', lw=1.2),
            )

        # Center text — total amount
        ax.text(0, 0.06, 'TOTAL', ha='center', va='center',
                fontsize=14, color='#ffffffaa', fontweight='bold')
        ax.text(0, -0.08, f'₪{total_sum:,.0f}', ha='center', va='center',
                fontsize=22, color='white', fontweight='bold')

        # Title
        ax.set_title('Monthly Spending', fontsize=18, color='white',
                     fontweight='bold', pad=20)

        plt.tight_layout()

        # Save to buffer
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        logger.error(f"Error generating pie chart: {type(e).__name__} - {e}")
        return None


def _escape_markdown(text: str) -> str:
    """
    Escape special Markdown characters in user-supplied text
    to prevent Telegram Markdown injection.
    """
    if not text:
        return ""
    for char in ['*', '_', '`', '[']:
        text = text.replace(char, f'\\{char}')
    return text


async def _safe_send(bot, chat_id, text, parse_mode='Markdown'):
    """
    Send a message, auto-truncating if it exceeds Telegram's 4096 char limit.
    Falls back to plain text if Markdown parsing fails.
    """
    if len(text) > TELEGRAM_MAX_LENGTH:
        text = text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n_(truncated)_"
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception:
        # Markdown might be malformed — retry as plain text
        try:
            return await bot.send_message(chat_id=chat_id, text=text, parse_mode=None)
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {type(e).__name__}")
            return None


def _private_only(func):
    """
    Decorator: only respond in private chats and check for ALLOWED_USER_ID if set.
    Includes null guards.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update:
            return
        
        # Determine user and chat from various update types
        user = update.effective_user
        chat = update.effective_chat
        
        if not chat or not user:
            return

        if chat.type != 'private':
            return
        
        # User ID validation (Single-Tenant Security)
        if ALLOWED_USER_ID and user.id != ALLOWED_USER_ID:
            logger.warning(f"Unauthorized access attempt by user {user.id}")
            await _safe_send(
                context.bot, 
                chat.id, 
                "⛔ *Access Denied*\n\nSorry, this is a private financial bot. You are not authorized to use it."
            )
            return

        return await func(update, context)
    return wrapper


# ── Command Handlers ──

@_private_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await _safe_send(
        context.bot, update.effective_chat.id,
        "🏦 *Welcome to FinTechBot Premium.* �\n\nI am your Personal Wealth Manager and Financial Intelligence Engine. My role is to log your cash flow, uncover behavioral spending patterns, and optimize your wealth over time.\n\n📝 *To log a transaction, simply text me naturally:*\n  • _\"Spent ₪150 on an Uber\"_\n  • _\"500 for groceries\"_\n  • _\"שילמתי 80 שקל על קפה\"_\n\n📊 Use /menu at any time to access your Analytics Dashboard. Type /help to view all available commands."
    )


@_private_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command."""
    text = (
        "� *FinTechBot Commands Protocol:*\n\n"
        "� *Log an Expense:* Just type naturally in English or Hebrew.\n"
        "  _\"Flight to London 450 EUR\"_\n"
        "  _\"שילמתי 200 על דלק\"_\n\n"
        "📊 /menu — Access your Analytics Dashboard & Insights\n"
        "⚙️ /settings — Configure your Wealth Profile\n"
        "💰 /budget `amount` — Define a monthly target (e.g., `/budget 5000`)\n"
        "↩️ /undo — Revert the last logged transaction\n"
        "📤 /export — Download your complete transaction ledger (CSV)\n"
        "🗑️ /deleteall — Wipe your financial data\n"
        "❓ /help — Documentation"
    )
    await _safe_send(context.bot, update.effective_chat.id, text)


@_private_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the interactive menu."""
    keyboard = [
        [InlineKeyboardButton("📜 Last Expenses", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
        [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart')],
        [InlineKeyboardButton("💡 AI Insights", callback_data='insights'), InlineKeyboardButton("⚙️ Settings", callback_data='settings_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if not update.message:
        return
    await update.message.reply_text('📊 *My Finances Menu:*', reply_markup=reply_markup, parse_mode='Markdown')


@_private_only
async def undo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes the most recent expense."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    last_id = db.get_last_expense_id(user_id)

    if not last_id:
        await _safe_send(context.bot, chat_id, "📭 No expenses to undo.")
        return

    success = db.delete_expense(user_id, last_id)
    if success:
        await _safe_send(context.bot, chat_id, "↩️ *Last expense removed!*")
    else:
        await _safe_send(context.bot, chat_id, "⚠️ Could not undo. Try again.")


@_private_only
async def budget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets or shows the monthly budget."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Check if user provided an amount
    if context.args:
        try:
            amount = float(context.args[0])
            if amount <= 0 or amount > 1_000_000:
                await _safe_send(context.bot, chat_id, "⚠️ Budget must be between 1 and 1,000,000.")
                return
            db.set_budget(user_id, amount)
            await _safe_send(context.bot, chat_id, f"💰 *Monthly budget set to {amount:.0f}!*")
        except ValueError as e:
            await _safe_send(context.bot, chat_id, f"⚠️ {str(e)}")
        except (IndexError):
            await _safe_send(context.bot, chat_id, "⚠️ Usage: /budget `5000`")
    else:
        budget = db.get_budget(user_id)
        if budget:
            total = db.get_monthly_summary(user_id)
            remaining = budget - total
            status = "✅" if remaining > 0 else "🚨"
            await _safe_send(
                context.bot, chat_id,
                f"💰 *Budget: {budget:.0f}*\n📊 Spent: {total:.0f}\n{status} Remaining: {remaining:.0f}"
            )
        else:
            await _safe_send(context.bot, chat_id, "💰 No budget set.\nUse /budget `5000` to set one.")


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
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the profile onboarding conversation."""
    user_id = update.effective_user.id
    
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
        
    profile = await asyncio.to_thread(db.get_profile, user_id)
    if profile:
        await message.reply_text(
            f"👤 *Your Wealth Profile:*\n"
            f"Age: {profile['age']}\n"
            f"Annual Income: {profile['yearly_income']:,.0f} {profile['currency']}\n"
            f"Objective / Context: {profile['additional_info']}\n\n"
            f"Let's calibrate your profile for sharper AI intelligence. 🧠\nFirst, what is your current age?\n\n_(Send /cancel at any time to abort)_",
            parse_mode='Markdown'
        )
    else:
        await message.reply_text(
            "Welcome to the Profile Calibration protocol. 🧠\n\nBy providing accurate data, the AI Wealth Manager can generate highly tailored mathematical models and behavioral insights for your spending.\n\nFirst, what is your current age?\n\n_(Send /cancel at any time to abort)_"
        )
    return ASK_AGE

async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        age = int(text)
        if not (13 <= age <= 120):
            raise ValueError
        context.user_data['age'] = age
        await update.message.reply_text("Excellent. Next, what is your total estimated annual income? (e.g. 150000)")
        return ASK_INCOME
    except ValueError:
        await update.message.reply_text("⚠️ Invalid format. Please enter a standard integer for your age (e.g., 30).")
        return ASK_AGE

async def ask_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        income = float(text)
        if income < 0:
            raise ValueError
        context.user_data['income'] = income
        await update.message.reply_text("Understood. Which fiat currency do you primarily hold? (e.g., NIS, USD, EUR, GBP)")
        return ASK_CURRENCY
    except ValueError:
        await update.message.reply_text("⚠️ Invalid format. Please enter a positive number for your annual income.")
        return ASK_INCOME

async def ask_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    if len(currency) > 10:
        await update.message.reply_text("⚠️ Currency code too long. Standard codes preferred (NIS, USD, EUR).")
        return ASK_CURRENCY
    
    context.user_data['currency'] = currency
    await update.message.reply_text("Finally, is there any specific financial context or objective I should optimize for? (e.g., 'Aggressively saving for a mortgage', 'Clearing $20k in student debt', 'LeanFIRE within 10 years')\n\nSend 'None' if you have no specific directives.")
    return ASK_INFO

async def ask_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info = update.message.text.strip()
    if info.lower() == 'none':
        info = ""
        
    age = context.user_data.get('age')
    income = context.user_data.get('income')
    currency = context.user_data.get('currency', 'NIS')
    user_id = update.effective_user.id
    
    try:
        await asyncio.to_thread(db.set_profile, user_id, age, income, currency, info)
        await update.message.reply_text(
            "✅ *Profile saved successfully!*\n\nThe AI Coach will now use this info for insights.\nUse /menu to view your dashboard.", 
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error saving profile: {e}")
        await update.message.reply_text("⚠️ There was an error saving your profile. Please try again later.")
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Profile setup cancelled. Your existing profile was not modified.")
    context.user_data.clear()
    return ConversationHandler.END



# ── Callback Handler ──

@_private_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses the CallbackQuery and updates the message text."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    telegram_id = query.from_user.id
    data = query.data

    # Handle "delete all" confirmation
    if data == 'confirm_delete_all':
        count = await asyncio.to_thread(db.delete_all_expenses, telegram_id)
        await query.edit_message_text(text=f"🗑️ *Done!* Deleted {count} expense(s).\n\nYou're starting fresh.", parse_mode='Markdown')
        return
    if data == 'cancel_delete_all':
        await query.edit_message_text(text="✅ Cancelled. Your expenses are safe.")
        return

    # Handle "delete all monthly" confirmation
    if data == 'confirm_delete_monthly':
        count = await asyncio.to_thread(db.delete_monthly_expenses, telegram_id)
        await query.edit_message_text(
            text=f"🗑️ *Done!* Deleted {count} expense(s) from this month.\n\nUse /menu to continue.",
            parse_mode='Markdown'
        )
        return
    if data == 'cancel_delete_monthly':
        await query.edit_message_text(text="✅ Cancelled. Your monthly expenses are safe.")
        return

    # Handle single delete callbacks (format: "del_123")
    if data.startswith("del_"):
        try:
            expense_id = int(data[4:])
            success = await asyncio.to_thread(db.delete_expense, telegram_id, expense_id)
            if success:

                await query.edit_message_text(text="🗑️ *Expense deleted!*\n\nUse /menu to refresh.", parse_mode='Markdown')
            else:
                await query.edit_message_text(text="⚠️ Could not delete. It may already be removed.")
        except (ValueError, Exception):
            await query.edit_message_text(text="⚠️ Error deleting expense.")
        return

    # Handle month drill-down callbacks (format: "month_2026_2")
    if data.startswith("month_"):
        try:
            parts = data.split('_')
            year = int(parts[1])
            month = int(parts[2])

            MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                           'July', 'August', 'September', 'October', 'November', 'December']

            expenses = await asyncio.to_thread(db.get_monthly_expenses, user_id=telegram_id, year=year, month=month)
            if not expenses:
                await query.edit_message_text(
                    text=f"📅 No expenses in {MONTH_NAMES[month]} {year}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='year_overview')]])
                )
                return

            total = sum(e[2] for e in expenses)
            text = f"📅 *{MONTH_NAMES[month]} {year}*\n💰 *Total: ₪{total:,.2f}*\n\n"

            # Group by category for a cleaner view
            cat_totals = {}
            for exp in expenses:
                cat = exp[3]
                cat_totals[cat] = cat_totals.get(cat, 0) + exp[2]

            # Category summary
            for cat, cat_total in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
                pct = (cat_total / total) * 100
                text += f"{_display_category(cat)}: *₪{cat_total:,.2f}* ({pct:.0f}%)\n"

            text += f"\n📝 *{len(expenses)} transaction(s):*\n\n"

            # Individual expenses (limit to avoid Telegram message length)
            for exp in expenses[:20]:
                date_short = exp[1][8:10]  # Day of month
                safe_desc = _escape_markdown(exp[4] or '') if len(exp) > 4 else ''
                text += f"  `{date_short}` ₪{exp[2]:,.2f} {_display_category(exp[3])}"
                if safe_desc:
                    text += f" _{safe_desc}_"
                text += "\n"

            if len(expenses) > 20:
                text += f"\n_...and {len(expenses) - 20} more_\n"

            buttons = [[InlineKeyboardButton("⬅️ Back to Year", callback_data='year_overview')]]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)
        except (ValueError, IndexError, Exception) as e:
            logger.error(f"Error in month drill-down: {type(e).__name__}")
            await query.edit_message_text(text="⚠️ Error loading month data.")
        return

    # Validate other callback data against whitelist
    if data not in VALID_CALLBACKS:
        logger.warning(f"Invalid callback data from user {telegram_id}: rejected")
        return

    try:
        if data == 'last_expenses':
            expenses = await asyncio.to_thread(db.get_recent_expenses, user_id=telegram_id, limit=5)
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
            # Sub-menu: This Month vs Yearly Overview
            keyboard = [
                [InlineKeyboardButton("📅 This Month", callback_data='this_month')],
                [InlineKeyboardButton("📆 Yearly Overview", callback_data='year_overview')],
                [InlineKeyboardButton("⬅️ Back to Menu", callback_data='back_to_menu')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="📊 *Expense History*\n\nChoose a view:",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

        elif data == 'back_to_menu':
            keyboard = [
                [InlineKeyboardButton("📜 Last Expenses", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
                [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart')],
                [InlineKeyboardButton("💡 AI Insights", callback_data='insights')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text='📊 *My Finances Menu:*', reply_markup=reply_markup, parse_mode='Markdown')

        elif data == 'this_month':
            expenses = await asyncio.to_thread(db.get_monthly_expenses, user_id=telegram_id)
            if not expenses:
                text = "📅 No expenses this month."
                await query.edit_message_text(text=text, parse_mode='Markdown')
            else:
                total = sum(e[2] for e in expenses)
                now = datetime.now()
                month_name = now.strftime('%B %Y')
                text = f"📅 *{month_name}*\n💰 *Total: ₪{total:,.2f}*\n\n"
                for exp in expenses:
                    date_short = exp[1][5:10]
                    text += f"• `{date_short}`: *₪{exp[2]:,.2f}* - {_display_category(exp[3])}\n"
                buttons = [
                    [InlineKeyboardButton("🗑️ Delete All This Month", callback_data='delete_all_monthly')],
                    [InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')],
                ]
                reply_markup = InlineKeyboardMarkup(buttons)
                await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

        elif data == 'year_overview':
            now = datetime.now()
            year = now.year
            month_totals = await asyncio.to_thread(db.get_yearly_month_totals, telegram_id, year)

            if not month_totals:
                await query.edit_message_text(text=f"📆 No expenses in {year} yet.")
                return

            grand_total = sum(month_totals.values())
            text = f"📆 *{year} Yearly Overview*\n💰 *Grand Total: ₪{grand_total:,.2f}*\n\n"

            MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

            buttons = []
            for m in range(1, 13):
                total = month_totals.get(m, 0)
                if total > 0:
                    pct = (total / grand_total) * 100
                    text += f"📌 *{MONTH_NAMES[m]}*: ₪{total:,.2f} ({pct:.0f}%)\n"
                    buttons.append([InlineKeyboardButton(
                        f"📅 {MONTH_NAMES[m]} — ₪{total:,.0f}",
                        callback_data=f'month_{year}_{m}'
                    )])

            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')])
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(text=text, parse_mode='Markdown', reply_markup=reply_markup)

        elif data == 'delete_all_monthly':
            keyboard = [
                [InlineKeyboardButton("🗑️ Yes, delete this month", callback_data='confirm_delete_monthly')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel_delete_monthly')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="⚠️ *Are you sure you want to delete ALL expenses for this month?*\n\nThis action *cannot be undone!*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )

        elif data == 'pie_chart':
            totals = await asyncio.to_thread(db.get_category_totals, user_id=telegram_id)
            if not totals:
                await query.edit_message_text(text="📉 No data for a chart yet.")
                return

            total_sum = sum(totals.values())
            if total_sum <= 0:
                await query.edit_message_text(text="📉 No valid data for a chart.")
                return

            await query.edit_message_text(text="📊 *Generating your chart...*", parse_mode='Markdown')

            # Create pie chart
            chart_buf = await asyncio.to_thread(_generate_pie_chart, totals, total_sum)

            caption = f"📊 *Spending Breakdown*\n💰 *Total: ₪{total_sum:,.2f}*\n\n"
            for cat, amt in sorted(totals.items(), key=lambda x: x[1], reverse=True):
                pct = (amt / total_sum) * 100
                caption += f"• {_display_category(cat)}: ₪{amt:,.2f} ({pct:.0f}%)\n"

            buttons = [[InlineKeyboardButton("⬅️ Back", callback_data='menu')]]

            if chart_buf is None:
                # Fallback to text if chart generation fails
                await query.edit_message_text(
                    text="⚠️ Chart generation failed, but here's your text breakdown:\n\n" + caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=chart_buf,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode='Markdown'
                )

        elif data == 'insights':
            status_msg = await query.edit_message_text(text="🧠 *Analyzing your spending...*\n\n_This might take a moment._", parse_mode='Markdown')

            try:
                # Fetch all needed context quickly
                totals = await asyncio.to_thread(db.get_category_totals, telegram_id)
                budget = await asyncio.to_thread(db.get_budget, telegram_id)
                recent = await asyncio.to_thread(db.get_recent_expenses, user_id=telegram_id, limit=5)
                profile = await asyncio.to_thread(db.get_profile, telegram_id)
                
                # Call enhanced insights
                insight = await asyncio.to_thread(
                    llm_helper.generate_insights,
                    totals=totals,
                    age=profile['age'] if profile else None,
                    yearly_income=profile['yearly_income'] if profile else None,
                    budget=budget,
                    recent_expenses=recent,
                    currency=profile.get('currency', 'NIS') if profile else 'NIS',
                    additional_info=profile.get('additional_info', '') if profile else None
                )

                if not insight or "⚠️" in insight:
                    await query.edit_message_text(text="⚠️ *AI Engine Unavailable*\n\nCould not generate insights at this time.", parse_mode='Markdown')
                    return

                # Format for better readability
                safe_insight = _escape_markdown(insight)
                await query.edit_message_text(text=f"💡 *FinTechBot Insights:*\n\n{safe_insight}", parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error generating insights callback: {e}")
                await query.edit_message_text(text="⚠️ *Error*\n\nThe AI ran into an issue processing your profile.", parse_mode='Markdown')

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
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Rate limiting check
    if _is_rate_limited(user_id):
        await _safe_send(context.bot, chat_id, "⏳ You're sending messages too fast. Please wait a moment.")
        return

    # Periodic cleanup of stale rate limit data
    _cleanup_rate_limit_data()

    # Input length check
    if len(user_text.strip()) == 0:
        return  # Silently ignore whitespace-only messages
    if len(user_text) > MAX_MESSAGE_LENGTH:
        await _safe_send(context.bot, chat_id, f"⚠️ Message too long. Please keep it under {MAX_MESSAGE_LENGTH} characters.")
        return

    processing_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ _Processing..._", parse_mode='Markdown')

    try:
        # 1. Parse with LLM (in background thread to avoid blocking)
        expense_data = await asyncio.to_thread(llm_helper.parse_expense, user_text)
        status = expense_data.get('status', 'not_expense') if expense_data else 'not_expense'

        if status == 'success':
            amount = expense_data.get('amount')
            category = expense_data.get('category')
            description = expense_data.get('description', '')

            # 2. Save to Database
            if amount and category:
                await asyncio.to_thread(db.add_expense, user_id, amount, category, description)

                # Escape description for safe Markdown display
                safe_desc = _escape_markdown(description)
                response_text = (
                    f"✅ *Expense Saved!*\n\n"
                    f"💰 Amount: *₪{amount:.2f}*\n"
                    f"📂 Category: {_display_category(category)}\n"
                    f"📝 Details: _{safe_desc}_\n"
                )

                # Show conversion info if currency was converted
                if expense_data.get('converted'):
                    orig_amount = expense_data.get('original_amount', amount)
                    orig_currency = expense_data.get('original_currency', 'NIS')
                    symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥'}
                    symbol = symbols.get(orig_currency, orig_currency)
                    response_text += f"\n💱 Converted from *{symbol}{orig_amount:.2f}* → *₪{amount:.2f}*\n"


                response_text += "\nUse /menu to see your dashboard."

                # Budget check
                budget = await asyncio.to_thread(db.get_budget, user_id)
                if budget:
                    total = await asyncio.to_thread(db.get_monthly_summary, user_id)
                    if total > budget:
                        response_text += f"\n\n🚨 *Budget alert!* You've spent {total:.0f}/{budget:.0f}"
                    elif total > budget * 0.8:
                        response_text += f"\n\n⚠️ *Heads up:* {total:.0f}/{budget:.0f} spent (80%+ of budget)"
            else:
                response_text = "⚠️ *Error*: Could not extract amount or category."

        elif status == 'no_category':
            # We found a number but couldn't figure out what it was for
            amt = expense_data.get('amount')
            if amt:
                response_text = (
                    f"🔢 Got *₪{amt:.0f}* but I'm not sure what it was for.\n"
                    f"Try: *\"₪{amt:.0f} on food\"* or *\"{amt:.0f} taxi\"*"
                )
            else:
                response_text = "🔢 I see a number but couldn't figure out the category.\nTry: *\"Spent 50 on food\"*"

        else:
            # not_expense — friendly non-financial response
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
        logger.error(f"Unexpected error for user {user_id}: {type(e).__name__}")
        response_text = "⚠️ Something went wrong. Please try again later."

    # Delete processing message and send result
    try:
        if processing_msg:
            await context.bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
    except Exception:
        pass
    await _safe_send(context.bot, chat_id, response_text)


def get_application():
    """Builds and configures the Telegram Application instance."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in .env file.")
        return None

    # Use a single shared application instance
    application = ApplicationBuilder().token(token).build()

    # ── Global Error Handler ──
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)
        if isinstance(update, Update) and update.effective_chat:
            try:
                await _safe_send(context.bot, update.effective_chat.id, "⚠️ An unexpected error occurred.")
            except Exception: pass

    application.add_error_handler(error_handler)

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start), 
            CommandHandler('settings', settings_command),
            CallbackQueryHandler(settings_command, pattern='^settings_menu$')
        ],
        states={
            ASK_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_age)],
            ASK_INCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_income)],
            ASK_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_currency)],
            ASK_INFO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_info)],
        },
        fallbacks=[CommandHandler('cancel', cancel_onboarding)]
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('menu', menu_command))
    application.add_handler(CommandHandler('undo', undo_command))
    application.add_handler(CommandHandler('budget', budget_command))
    application.add_handler(CommandHandler('export', export_command))
    application.add_handler(CommandHandler('deleteall', deleteall_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    return application


if __name__ == '__main__':
    # Standard Polling startup (for local development)
    db.init_db()
    app = get_application()
    if app:
        logger.info("Bot is starting (Polling)...")
        app.run_polling(drop_pending_updates=True)

