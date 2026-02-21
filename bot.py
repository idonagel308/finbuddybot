import os
from datetime import datetime
import io
import logging
import time
import traceback
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend (no GUI needed)
import matplotlib.pyplot as plt
from functools import wraps
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

# Suppress httpx logs that leak the bot token in URLs
logging.getLogger("httpx").setLevel(logging.WARNING)

import database as db
import llm_helper

# --- Constants ---
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGE_LENGTH = 500
TELEGRAM_MAX_LENGTH = 4096  # Telegram's hard limit for a single message
_user_message_timestamps = defaultdict(list)

# Whitelist of valid callback data values
VALID_CALLBACKS = {'last_expenses', 'monthly_list', 'this_month', 'year_overview', 'pie_chart', 'insights', 'delete_all_monthly', 'back_to_menu'}

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
        import numpy as np
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
    """Decorator: only respond in private chats. Includes null guards."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update or not update.effective_chat:
            return
        if update.effective_chat.type != 'private':
            return
        if not update.effective_user:
            return
        return await func(update, context)
    return wrapper


# ── Command Handlers ──

@_private_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await _safe_send(
        context.bot, update.effective_chat.id,
        "👋 *Welcome to FinTechBot!* 🤖💰\n\nI can help you track your expenses and save money.\n\n📝 *Try it:* Send me an expense like:\n*\"Spent 50 shekels on pizza\"*\n*\"Taxi to work 40\"*\n\nThen use /menu to see your stats! 📊\nType /help for all commands."
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
    await _safe_send(context.bot, update.effective_chat.id, text)


@_private_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the interactive menu."""
    keyboard = [
        [InlineKeyboardButton("📜 Last Expenses", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
        [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart')],
        [InlineKeyboardButton("💡 AI Insights", callback_data='insights')],
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
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets or shows the user's age and wage."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if context.args and len(context.args) == 2:
        try:
            age = int(context.args[0])
            wage = float(context.args[1])
            # Validate ranges
            if not (13 <= age <= 120):
                await _safe_send(context.bot, chat_id, "⚠️ Age must be between 13 and 120.")
                return
            if not (0 < wage <= 1_000_000):
                await _safe_send(context.bot, chat_id, "⚠️ Wage must be between 1 and 1,000,000.")
                return
            db.set_profile(user_id, age, wage)
            await _safe_send(context.bot, chat_id, f"👤 *Profile Updated!*\nAge: {age}\nWage: {wage:.0f} NIS")
        except ValueError:
            await _safe_send(context.bot, chat_id, "⚠️ Usage: /profile `<age> <wage>`\nExample: `/profile 25 12000`")
    else:
        profile = db.get_profile(user_id)
        if profile:
            await _safe_send(
                context.bot, chat_id,
                f"👤 *Your Profile:*\nAge: {profile['age']}\nWage: {profile['wage']:.0f} NIS\n\nTo update: `/profile <age> <wage>`"
            )
        else:
            await _safe_send(context.bot, chat_id, "👤 No profile set.\nUse `/profile <age> <wage>` to get better AI insights.")



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

    # Handle "delete all monthly" confirmation
    if data == 'confirm_delete_monthly':
        count = db.delete_monthly_expenses(telegram_id)
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
            success = db.delete_expense(telegram_id, expense_id)
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

            expenses = db.get_monthly_expenses(user_id=telegram_id, year=year, month=month)
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
            expenses = db.get_monthly_expenses(user_id=telegram_id)
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
            month_totals = db.get_yearly_month_totals(telegram_id, year)

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
            totals = db.get_category_totals(user_id=telegram_id)
            if not totals:
                await query.edit_message_text(text="📉 No data for a chart yet.")
                return

            total_sum = sum(totals.values())
            if total_sum <= 0:
                await query.edit_message_text(text="📉 No valid data for a chart.")
                return

            await query.edit_message_text(text="📊 *Generating your chart...*", parse_mode='Markdown')

            # Generate pie chart image
            chart_buf = _generate_pie_chart(totals, total_sum)

            # Send chart as photo
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=chart_buf,
                caption=f"📊 *Monthly Spending Breakdown*\nTotal: *₪{total_sum:,.2f}*",
                parse_mode='Markdown'
            )

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
        # 1. Parse with LLM
        expense_data = llm_helper.parse_expense(user_text)
        status = expense_data.get('status', 'not_expense') if expense_data else 'not_expense'

        if status == 'success':
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
                budget = db.get_budget(user_id)
                if budget:
                    total = db.get_monthly_summary(user_id)
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

    # ── Global Error Handler ──
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        """Catches any uncaught exception across all handlers."""
        logger.error(f"Unhandled exception: {context.error}", exc_info=context.error)
        # Try to notify the user if possible
        if isinstance(update, Update) and update.effective_chat:
            try:
                await _safe_send(
                    context.bot, update.effective_chat.id,
                    "⚠️ An unexpected error occurred. Please try again."
                )
            except Exception:
                pass  # Can't even send error msg — just log and move on

    application.add_error_handler(error_handler)

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
    application.run_polling(drop_pending_updates=True)

