import os
import io
import asyncio
import logging
import time
from datetime import datetime

from functools import wraps
from collections import defaultdict
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from core.config import (
    logger, MAX_MESSAGES_PER_MINUTE, MAX_MESSAGE_LENGTH, TELEGRAM_MAX_LENGTH,
    ALLOWED_USER_ID, VALID_CALLBACKS, CATEGORY_EMOJIS
)
import services.database as db
import services.llm_helper as llm_helper

_user_message_timestamps = defaultdict(list)


def _display_category(category: str) -> str:
    """Convert a clean category string to an emoji-decorated display string."""
    # If it already has an emoji (legacy data), pass through as-is
    if any(ord(c) > 0xFFFF for c in category):
        return category
    emoji = CATEGORY_EMOJI.get(category, '❓')
    return f"{emoji} {category}"

def _get_category_keyboard() -> InlineKeyboardMarkup:
    """Returns a grid of category buttons for manual selection."""
    main_cats = ['Food', 'Transport', 'Shopping', 'Entertainment', 'Housing', 'Health', 'Education', 'Other']
    buttons = []
    # 2 columns per row
    for i in range(0, len(main_cats), 2):
        row = []
        for cat in main_cats[i:i+2]:
            row.append(InlineKeyboardButton(_display_category(cat), callback_data=f'cat_select_{cat}'))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_cat_select')])
    return InlineKeyboardMarkup(buttons)


# ── Profile Cache ──
# Caches db.get_profile results in-process for PROFILE_CACHE_TTL seconds.
# This eliminates a DB read on every _safe_send / _safe_edit call (which
# both check language to decide whether to translate). For English-only
# users this was pure wasted I/O on every single bot response.
_PROFILE_CACHE_TTL = 300  # 5 minutes
_profile_cache: dict = {}  # {user_id: (profile_dict, timestamp)}


def _get_cached_profile(user_id: int) -> dict | None:
    """Return a cached profile, or fetch from DB and cache it."""
    now = time.monotonic()
    entry = _profile_cache.get(user_id)
    if entry:
        profile, ts = entry
        if now - ts < _PROFILE_CACHE_TTL:
            return profile
    # Cache miss or expired — fetch from DB
    try:
        profile = db.get_profile(user_id)
    except Exception:
        profile = None
    _profile_cache[user_id] = (profile, now)
    return profile


def _invalidate_profile_cache(user_id: int):
    """Call after any db.set_profile or db.set_budget write to ensure freshness."""
    _profile_cache.pop(user_id, None)


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
        fig.savefig(buf, format='png', dpi=90, bbox_inches='tight',
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


async def _safe_send(bot, chat_id, text, parse_mode='Markdown', reply_markup=None):
    """
    Send a message, auto-truncating if it exceeds Telegram's 4096 char limit.
    Dynamically translates the message and buttons into the user's preferred language.
    Falls back to plain text if Markdown parsing fails.
    Uses the profile cache to avoid a DB read on every call.
    """
    try:
        profile = _get_cached_profile(chat_id)
        target_lang = profile.get('language', 'English') if profile else 'English'
    except Exception:
        target_lang = 'English'

    if target_lang.lower() not in ['english', 'en', '']:
        text = await asyncio.to_thread(llm_helper.translate, text, target_lang)
        if reply_markup and getattr(reply_markup, 'inline_keyboard', None):
            new_kb = []
            for row in reply_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    tr_text = await asyncio.to_thread(llm_helper.translate, btn.text, target_lang)
                    if asyncio.iscoroutine(tr_text):
                        tr_text = await tr_text
                    # Property Preservation: Copy all relevant attributes from the original button
                    button_kwargs = {'text': tr_text}
                    for attr in ['callback_data', 'url', 'web_app', 'login_url', 'switch_inline_query', 'switch_inline_query_current_chat']:
                        val = getattr(btn, attr, None)
                        if val:
                            button_kwargs[attr] = val
                    new_row.append(InlineKeyboardButton(**button_kwargs))
                new_kb.append(new_row)
            reply_markup = InlineKeyboardMarkup(new_kb)

    if not isinstance(text, str):
        text = await text if asyncio.iscoroutine(text) else str(text)

    if len(text) > TELEGRAM_MAX_LENGTH:
        text = text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n_(truncated)_"
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        # Markdown might be malformed — retry as plain text
        try:
            return await bot.send_message(chat_id=chat_id, text=text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {type(e).__name__}")
            return None



async def _safe_edit(query, chat_id, text, parse_mode='Markdown', reply_markup=None):
    """Dynamically translates and edits a message. Uses the profile cache."""
    try:
        profile = _get_cached_profile(chat_id)
        target_lang = profile.get('language', 'English') if profile else 'English'
    except Exception:
        target_lang = 'English'

    if target_lang.lower() not in ['english', 'en', '']:
        text = await asyncio.to_thread(llm_helper.translate, text, target_lang)
        if reply_markup and getattr(reply_markup, 'inline_keyboard', None):
            new_kb = []
            for row in reply_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    tr_text = await asyncio.to_thread(llm_helper.translate, btn.text, target_lang)
                    new_row.append(InlineKeyboardButton(tr_text, callback_data=btn.callback_data))
                new_kb.append(new_row)
            reply_markup = InlineKeyboardMarkup(new_kb)

    if len(text) > TELEGRAM_MAX_LENGTH:
        text = text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n_(truncated)_"
    try:
        return await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except Exception:
        try:
            return await query.edit_message_text(text=text, parse_mode=None, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to edit message for {chat_id}: {type(e).__name__}")
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

def _get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the primary dashboard inline keyboard."""
    
    # URL of your mounted FastAPI static webapp (can be configurable via .env in production)
    from telegram import WebAppInfo
    webapp_url = os.getenv("WEBAPP_URL", "https://your-ngrok-url.ngrok-free.app/webapp")
    
    keyboard = [
        [InlineKeyboardButton("🌐 Open Web Dashboard", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton("📜 Last Transactions", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
        [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart'), InlineKeyboardButton("💡 AI Context Insights", callback_data='insights')],
        [InlineKeyboardButton("⚙️ Settings & Tools", callback_data='settings_tools')],
    ]
    return InlineKeyboardMarkup(keyboard)

@_private_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    await _safe_send(context.bot, update.effective_chat.id, 
        "🏦 *Welcome to FinTechBot Premium.*\n\n"
        "I am your Personal Wealth Manager and Financial Intelligence Engine.\n\n"
        "📝 *To log a transaction, simply text me naturally:*\n"
        "  • _\"Spent ₪150 on an Uber\"_\n"
        "  • _\"100 for groceries\"_\n\n"
        "🌐 *Language & Settings:*\n"
        "You can choose my response language by tapping ⚙️ Settings below to set up your profile.\n\n"
        "📊 *Your Analytics Dashboard:*",
        reply_markup=_get_main_menu_keyboard(),
        parse_mode='Markdown'
    )


@_private_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command."""
    await _safe_send(context.bot, update.effective_chat.id, 
        "🤖 *FinTechBot Protocol:*\n\n"
        "To log an expense, simply type it out. E.g., _\"Flight to London 450 EUR\"_.\n\n"
        "You can manage your analytics and settings using the Main Dashboard below:",
        reply_markup=_get_main_menu_keyboard(),
        parse_mode='Markdown'
    )


@_private_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the interactive menu."""
    if not update.message:
        return
    await _safe_send(context.bot, update.effective_chat.id, '📊 *My Finances Dashboard:*', reply_markup=_get_main_menu_keyboard(), parse_mode='Markdown')


@_private_only
async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Directly opens the Web App Dashboard."""
    if not update.message:
        return
    
    from telegram import WebAppInfo
    webapp_url = os.getenv("WEBAPP_URL", "https://your-ngrok-url.ngrok-free.app/webapp")
    keyboard = [[InlineKeyboardButton("Open Dashboard", web_app=WebAppInfo(url=webapp_url))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await _safe_send(
        context.bot, 
        update.effective_chat.id, 
        "🚀 *Launch your Interactive Dashboard below:*", 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )


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
            total, _ = db.get_monthly_summary(user_id)
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


# ── Settings Helpers ──

def _profile_defaults(profile: dict | None) -> dict:
    """Returns a profile dict with safe fallback defaults."""
    if not profile:
        return {'age': 18, 'yearly_income': 0, 'currency': 'NIS', 'language': 'English', 'additional_info': ''}
    return {
        'age': profile.get('age') or 18,
        'yearly_income': profile.get('yearly_income') or 0,
        'currency': profile.get('currency') or 'NIS',
        'language': profile.get('language') or 'English',
        'additional_info': profile.get('additional_info') or '',
    }


def _get_settings_keyboard(profile: dict | None) -> InlineKeyboardMarkup:
    """Builds the settings hub keyboard showing current values for each field."""
    p = _profile_defaults(profile)
    lang    = p['language']
    cur     = p['currency']
    age     = str(p['age']) if p['age'] != 18 or profile else '— Not set'
    income  = f"{p['yearly_income']:,.0f}" if p['yearly_income'] else '— Not set'
    goals   = '✅ Set' if p['additional_info'] else '— Not set'
    keyboard = [
        [InlineKeyboardButton(f"🌐 Language: {lang}", callback_data='settings_set_lang')],
        [InlineKeyboardButton(f"💱 Currency: {cur}", callback_data='settings_set_currency')],
        [InlineKeyboardButton("💰 Set Monthly Budget", callback_data='settings_set_budget')],
        [InlineKeyboardButton(f"👤 Age: {age}", callback_data='settings_set_age'),
         InlineKeyboardButton(f"💵 Income: {income}", callback_data='settings_set_income')],
        [InlineKeyboardButton(f"🎯 Goals: {goals}", callback_data='settings_set_goals')],
        [InlineKeyboardButton("📤 Export CSV", callback_data='export_csv'),
         InlineKeyboardButton("🗑️ Delete All Data", callback_data='delete_all')],
        [InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _show_settings(target, chat_id: int, user_id: int, edit: bool = False):
    """Renders the settings hub. Use edit=True when updating from a CallbackQuery."""
    profile = await asyncio.to_thread(db.get_profile, user_id)
    text = (
        "⚙️ *Settings & Profile*\n\n"
        "_Tap any setting to change it individually._\n"
        "_Your profile is used by the AI Insights engine on every analysis._"
    )
    keyboard = _get_settings_keyboard(profile)
    if edit:
        await target.edit_message_text(text=text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await _safe_send(target, chat_id, text, reply_markup=keyboard)


@_private_only
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /settings — shows the inline settings hub."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    await _show_settings(context.bot, chat_id, user_id, edit=False)


async def _handle_setting_input(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str) -> bool:
    """
    Processes a free-text message that is a pending settings value.
    Called by handle_message when context.user_data['awaiting_setting'] is set.
    Always clears the flag and returns True (message consumed).
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    context.user_data.pop('awaiting_setting', None)

    try:
        profile = await asyncio.to_thread(db.get_profile, user_id)
        p = _profile_defaults(profile)

        if setting_key == 'age':
            age = int(text)
            if not (13 <= age <= 120):
                raise ValueError("Age out of range")
            await asyncio.to_thread(db.set_profile, user_id, age, p['yearly_income'], p['currency'], p['language'], p['additional_info'])
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, f"✅ *Age updated to {age}.*", parse_mode='Markdown')

        elif setting_key == 'income':
            income = float(text.replace(',', '').replace(' ', ''))
            if income < 0:
                raise ValueError("Income must be positive")
            await asyncio.to_thread(db.set_profile, user_id, p['age'], income, p['currency'], p['language'], p['additional_info'])
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, f"✅ *Annual income updated to {income:,.0f}.*", parse_mode='Markdown')

        elif setting_key == 'goals':
            info = '' if text.lower() == 'none' else text
            await asyncio.to_thread(db.set_profile, user_id, p['age'], p['yearly_income'], p['currency'], p['language'], info)
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, "✅ *Financial goals updated.*", parse_mode='Markdown')

        elif setting_key == 'budget':
            amount = float(text.replace(',', '').replace(' ', ''))
            if amount <= 0 or amount > db.MAX_AMOUNT:
                raise ValueError("Budget out of range")
            await asyncio.to_thread(db.set_budget, user_id, amount)
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, f"✅ *Monthly budget set to {amount:,.0f}.*", parse_mode='Markdown')

        elif setting_key == 'lang_custom':
            if len(text) > 50:
                await _safe_send(context.bot, chat_id, "⚠️ Language name too long. Please use a standard name like 'Italian'.")
                return True
            await asyncio.to_thread(db.set_profile, user_id, p['age'], p['yearly_income'], p['currency'], text, p['additional_info'])
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, f"✅ *Language set to {text}.*", parse_mode='Markdown')

        elif setting_key == 'currency_custom':
            cur = text.upper()
            if len(cur) > 10:
                await _safe_send(context.bot, chat_id, "⚠️ Code too long. Use standard codes like CHF, TRY, BRL.")
                return True
            await asyncio.to_thread(db.set_profile, user_id, p['age'], p['yearly_income'], cur, p['language'], p['additional_info'])
            _invalidate_profile_cache(user_id)
            await _safe_send(context.bot, chat_id, f"✅ *Currency set to {cur}.*", parse_mode='Markdown')

    except (ValueError, TypeError):
        hints = {
            'age': 'a number between 13 and 120 _(e.g. 30)_',
            'income': 'a positive number _(e.g. 120000)_',
            'budget': 'a positive amount _(e.g. 5000)_',
            'lang_custom': 'a language name _(e.g. Italian)_',
            'currency_custom': 'a 3-letter currency code _(e.g. CHF)_',
        }
        hint = hints.get(setting_key, 'a valid value')
        await _safe_send(context.bot, chat_id, f"⚠️ Invalid input. Please send {hint}.", parse_mode='Markdown')
        return True

    # Re-show the settings hub after a successful update
    await _show_settings(context.bot, chat_id, user_id, edit=False)
    return True



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

    # Handle language quick-pick callbacks (e.g. "lang_English")
    if data.startswith("lang_"):
        lang_name = data[5:]
        valid_langs = {'English', 'Hebrew', 'Spanish', 'French', 'German', 'Russian', 'Arabic', 'Portuguese'}
        if lang_name in valid_langs:
            try:
                profile = await asyncio.to_thread(db.get_profile, telegram_id)
                p = _profile_defaults(profile)
                await asyncio.to_thread(db.set_profile, telegram_id, p['age'], p['yearly_income'], p['currency'], lang_name, p['additional_info'])
                _invalidate_profile_cache(telegram_id)
                await _show_settings(query, telegram_id, telegram_id, edit=True)
            except Exception:
                await query.edit_message_text(text="⚠️ Error updating language. Please try again.")
        return

    # Handle currency quick-pick callbacks (e.g. "cur_USD")
    if data.startswith("cur_"):
        cur_code = data[4:]
        valid_curs = {'NIS', 'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY'}
        if cur_code in valid_curs:
            try:
                profile = await asyncio.to_thread(db.get_profile, telegram_id)
                p = _profile_defaults(profile)
                await asyncio.to_thread(db.set_profile, telegram_id, p['age'], p['yearly_income'], cur_code, p['language'], p['additional_info'])
                _invalidate_profile_cache(telegram_id)
                await _show_settings(query, telegram_id, telegram_id, edit=True)
            except Exception:
                await query.edit_message_text(text="⚠️ Error updating currency. Please try again.")
        return

    # Handle category selection callbacks
    if data.startswith("cat_select_"):
        cat_name = data[11:]
        pending = context.user_data.get('pending_expense')
        if not pending:
            await query.edit_message_text(
                text="⚠️ Session expired or invalid category selection. Please send the expense again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
            )
            return

        amount = pending['amount']
        description = pending['description']

        # Save to Database
        await asyncio.to_thread(db.add_expense, telegram_id, amount, cat_name, description)
        context.user_data.pop('pending_expense', None)

        safe_desc = _escape_markdown(description)
        response_text = (
            f"✅ *Expense Saved!*\n\n"
            f"💰 Amount: 🔴 *₪{amount:.2f}*\n"
            f"📂 Category: {_display_category(cat_name)}\n"
            f"📝 Details: _{safe_desc}_\n\n"
            f"Use /menu to see your dashboard."
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Undo", callback_data='undo_last'), InlineKeyboardButton("📊 Dashboard", callback_data='back_to_menu')]
        ])
        await query.edit_message_text(text=response_text, parse_mode='Markdown', reply_markup=reply_markup)
        return

    if data == 'cancel_cat_select':
        context.user_data.pop('pending_expense', None)
        await query.edit_message_text(
            text="❌ Expense cancelled.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
        )
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
                await query.edit_message_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]])
                )
            else:
                text = "📜 *Last 5 Expenses:*\n\n"
                buttons = []
                for exp in expenses:
                    date_short = exp[1][5:10]
                    safe_desc = _escape_markdown(exp[4] or '')
                    text += f"🗓️ `{date_short}` | 💰 *{exp[2]}* | {_display_category(exp[3])}\n_{safe_desc}_\n\n"
                    buttons.append([InlineKeyboardButton(f"🗑️ Delete {exp[2]} {_display_category(exp[3])}", callback_data=f"del_{exp[0]}")])
                buttons.append([InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')])
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
            from telegram import WebAppInfo
            webapp_url = os.getenv("WEBAPP_URL", "https://your-ngrok-url.ngrok-free.app/webapp")
            keyboard = [
                [InlineKeyboardButton("🌐 Open Web Dashboard", web_app=WebAppInfo(url=webapp_url))],
                [InlineKeyboardButton("📜 Last Transactions", callback_data='last_expenses'), InlineKeyboardButton("📅 Monthly / Yearly", callback_data='monthly_list')],
                [InlineKeyboardButton("📊 Category Pie Chart", callback_data='pie_chart'), InlineKeyboardButton("💡 AI Context Insights", callback_data='insights')],
                [InlineKeyboardButton("⚙️ Settings & Tools", callback_data='settings_tools')],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text='📊 *My Finances Dashboard:*', reply_markup=reply_markup, parse_mode='Markdown')

        elif data == 'this_month' or data.startswith('month_'):
            if data == 'this_month':
                now = datetime.now()
                year, month = now.year, now.month
            else:
                _, y_str, m_str = data.split('_')
                year, month = int(y_str), int(m_str)

            spent, income = await asyncio.to_thread(db.get_monthly_summary, telegram_id, year, month)
            budget = await asyncio.to_thread(db.get_budget, telegram_id)
            net = income - spent

            MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                           'July', 'August', 'September', 'October', 'November', 'December']

            text = f"📅 *{MONTH_NAMES[month]} {year}*\n\n"
            text += f"📥 *Income:* 🟢 ₪{income:,.2f}\n"
            text += f"📤 *Expenses:* 🔴 ₪{spent:,.2f}\n"
            text += f"🧮 *Net Flow:* ₪{net:,.2f}\n\n"

            if budget and data == 'this_month':
                pct = (spent / budget) * 100
                bar_len = 10
                filled = min(bar_len, int((pct / 100) * bar_len))
                bar = "▮" * filled + "▯" * (bar_len - filled)
                text += f"📊 *Budget:* [{bar}] {pct:.0f}%\n"
                text += f"_(₪{spent:,.2f} of ₪{budget:,.2f})_\n\n"

            text += "🔽 *Recent Transactions:*\n"
            
            expenses = await asyncio.to_thread(db.get_monthly_expenses, telegram_id, year, month)
            if not expenses:
                text += "_No transactions logged._"
            else:
                for exp in expenses[:5]:
                    d_str = _format_date(exp[1])
                    icon = "🟢" if exp[5] == "income" else "🔴"
                    cat = _display_category(exp[3])
                    desc = f" — _{_escape_markdown(exp[4])}_" if exp[4] else ""
                    text += f"• {d_str} | {cat}: {icon} ₪{exp[2]:.0f}{desc}\n"

            buttons = [
                [InlineKeyboardButton("🗑️ Delete All This Month", callback_data='delete_all_monthly')],
                [InlineKeyboardButton("⬅️ Back", callback_data='monthly_list')],
            ] if data == 'this_month' else [
                [InlineKeyboardButton("⬅️ Back to Year", callback_data='year_overview')]
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
            # get_expense_totals() returns flat {category: float} (expense-only)
            # This is the correct format for the pie chart — never use get_category_totals() here.
            totals = await asyncio.to_thread(db.get_expense_totals, telegram_id)
            if not totals:
                await query.edit_message_text(text="📉 No data for a chart yet.")
                return

            total_sum = sum(totals.values())
            if total_sum <= 0:
                await query.edit_message_text(text="📉 No valid data for a chart.")
                return

            await query.edit_message_text(text="📊 *Generating Expense Breakdown...*", parse_mode='Markdown')

            # Create pie chart
            chart_buf = await asyncio.to_thread(_generate_pie_chart, totals, total_sum)

            caption = f"📊 *Expense Breakdown*\n🔴 *Total Spent: ₪{total_sum:,.2f}*\n\n"
            for cat, amt in sorted(totals.items(), key=lambda x: x[1], reverse=True):
                pct = (amt / total_sum) * 100
                caption += f"• {_display_category(cat)}: ₪{amt:,.2f} ({pct:.0f}%)\n"

            buttons = [[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]]

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
                # get_category_totals returns {cat: {"expenses": X, "income": Y}}
                # We flatten it to {cat: float} for the LLM insights function
                raw_totals = await asyncio.to_thread(db.get_category_totals, telegram_id)
                totals = {cat: v.get('expenses', 0) for cat, v in raw_totals.items() if v.get('expenses', 0) > 0}
                if not totals:
                    await query.edit_message_text(text="💡 No spending data yet. Log some expenses first!", parse_mode='Markdown')
                    return

                budget = await asyncio.to_thread(db.get_budget, telegram_id)
                recent = await asyncio.to_thread(db.get_recent_expenses, user_id=telegram_id, limit=5)
                profile = await asyncio.to_thread(db.get_profile, telegram_id)

                # Build kwargs safely — profile may be None (new user)
                insight = await asyncio.to_thread(
                    llm_helper.generate_insights,
                    totals=totals,
                    age=profile.get('age') if profile else None,
                    yearly_income=profile.get('yearly_income') if profile else None,
                    budget=budget,
                    recent_expenses=recent,
                    currency=profile.get('currency', 'NIS') if profile else 'NIS',
                    language=profile.get('language', 'English') if profile else 'English',
                    additional_info=profile.get('additional_info', '') if profile else None
                )

                if not insight or "⚠️" in insight:
                    await query.edit_message_text(text="⚠️ *AI Engine Unavailable*\n\nCould not generate insights at this time.", parse_mode='Markdown')
                    return

                # SAVE for WebApp Sync
                now = datetime.now()
                await asyncio.to_thread(db.save_insight, telegram_id, now.year, now.month, insight)

                safe_insight = _escape_markdown(insight)
                await query.edit_message_text(text=f"💡 *FinTechBot Insights:*\n\n{safe_insight}", parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Error generating insights callback: {e}")
                await query.edit_message_text(text="⚠️ *Error*\n\nThe AI ran into an issue processing your profile.", parse_mode='Markdown')

        elif data in ('settings_menu', 'settings_tools'):
            # Both legacy and new entry point — always show the hub
            context.user_data.pop('awaiting_setting', None)
            await _show_settings(query, telegram_id, telegram_id, edit=True)

        elif data == 'settings_set_lang':
            keyboard = [
                [InlineKeyboardButton("🇬🇧 English", callback_data='lang_English'), InlineKeyboardButton("🇮🇱 Hebrew", callback_data='lang_Hebrew')],
                [InlineKeyboardButton("🇪🇸 Spanish", callback_data='lang_Spanish'), InlineKeyboardButton("🇫🇷 French", callback_data='lang_French')],
                [InlineKeyboardButton("🇩🇪 German", callback_data='lang_German'), InlineKeyboardButton("🇷🇺 Russian", callback_data='lang_Russian')],
                [InlineKeyboardButton("🇸🇦 Arabic", callback_data='lang_Arabic'), InlineKeyboardButton("🇧🇷 Portuguese", callback_data='lang_Portuguese')],
                [InlineKeyboardButton("✏️ Other (type it)", callback_data='settings_edit_lang_custom')],
                [InlineKeyboardButton("⬅️ Back", callback_data='settings_tools')],
            ]
            await query.edit_message_text(
                text="🌐 *Choose your language:*\n\n_AI insights and all bot responses will be in this language._",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'settings_edit_lang_custom':
            context.user_data['awaiting_setting'] = 'lang_custom'
            await query.edit_message_text(
                text="✏️ *Type your preferred language:*\n_(e.g. Italian, Thai, Turkish)_",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_currency':
            keyboard = [
                [InlineKeyboardButton("🇮🇱 NIS ₪", callback_data='cur_NIS'), InlineKeyboardButton("🇺🇸 USD $", callback_data='cur_USD')],
                [InlineKeyboardButton("🇪🇺 EUR €", callback_data='cur_EUR'), InlineKeyboardButton("🇬🇧 GBP £", callback_data='cur_GBP')],
                [InlineKeyboardButton("🇨🇦 CAD", callback_data='cur_CAD'), InlineKeyboardButton("🇦🇺 AUD", callback_data='cur_AUD')],
                [InlineKeyboardButton("🇯🇵 JPY ¥", callback_data='cur_JPY')],
                [InlineKeyboardButton("✏️ Other (type it)", callback_data='settings_edit_currency_custom')],
                [InlineKeyboardButton("⬅️ Back", callback_data='settings_tools')],
            ]
            await query.edit_message_text(
                text="💱 *Choose your primary currency:*\n\n_Used for income tracking and AI insights._",
                parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'settings_edit_currency_custom':
            context.user_data['awaiting_setting'] = 'currency_custom'
            await query.edit_message_text(
                text="✏️ *Type your currency code:*\n_(e.g. CHF, TRY, BRL)_",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_budget':
            budget = await asyncio.to_thread(db.get_budget, telegram_id)
            total, _ = await asyncio.to_thread(db.get_monthly_summary, telegram_id)
            context.user_data['awaiting_setting'] = 'budget'
            budget_text = f"Current: *{budget:,.0f}*, spent *{total:,.0f}* this month." if budget else "_No budget set yet._"
            await query.edit_message_text(
                text=f"💰 *Set Monthly Budget*\n\n{budget_text}\n\n✏️ Type your new monthly budget amount:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_age':
            profile = await asyncio.to_thread(db.get_profile, telegram_id)
            current = f"Current: *{profile['age']}*" if profile and profile.get('age') else "_Not set yet._"
            context.user_data['awaiting_setting'] = 'age'
            await query.edit_message_text(
                text=f"👤 *Set Your Age*\n\n{current}\n\n✏️ Type your age (13–120):",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_income':
            profile = await asyncio.to_thread(db.get_profile, telegram_id)
            currency = profile.get('currency', 'NIS') if profile else 'NIS'
            income_val = profile.get('yearly_income', 0) if profile else 0
            current = f"Current: *{income_val:,.0f} {currency} / year*" if income_val else "_Not set yet._"
            context.user_data['awaiting_setting'] = 'income'
            await query.edit_message_text(
                text=f"💵 *Set Annual Income*\n\n{current}\n\n✏️ Type your yearly income:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'settings_set_goals':
            profile = await asyncio.to_thread(db.get_profile, telegram_id)
            current = f"_Current:_ {_escape_markdown(profile['additional_info'])}" if profile and profile.get('additional_info') else "_Not set yet._"
            context.user_data['awaiting_setting'] = 'goals'
            await query.edit_message_text(
                text=(
                    f"🎯 *Financial Goals & Context*\n\n{current}\n\n"
                    "✏️ Describe your financial goals:\n"
                    "_e.g. 'Saving for a mortgage', 'Clearing student debt', 'FIRE by 40'_\n\n"
                    "_(Send 'none' to clear)_"
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data='settings_tools')]])
            )

        elif data == 'undo_last':
            last_id = await asyncio.to_thread(db.get_last_expense_id, telegram_id)
            if not last_id:
                await query.edit_message_text(text="📭 No expenses to undo.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]]))
            else:
                success = await asyncio.to_thread(db.delete_expense, telegram_id, last_id)
                if success:
                    await query.edit_message_text(
                        text="↩️ *Last expense removed!*",
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]])
                    )
                else:
                    await query.edit_message_text(text="⚠️ Could not undo. Try again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]]))

        elif data == 'export_csv':
            csv_data = await asyncio.to_thread(db.export_expenses_csv, telegram_id)
            if not csv_data or csv_data.strip() == 'Date,Amount,Category,Description':
                await query.edit_message_text(text="📭 No expenses to export.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data='back_to_menu')]]))
            else:
                file = io.BytesIO(csv_data.encode('utf-8'))
                file.name = "expenses.csv"
                await context.bot.send_document(chat_id=telegram_id, document=file, caption="📤 *Your expenses export*", parse_mode='Markdown')
                await query.edit_message_text(text="✅ Export sent successfully!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Dashboard", callback_data='back_to_menu')]]))

        elif data == 'delete_all':
            keyboard = [
                [InlineKeyboardButton("🗑️ Yes, wipe EVERYTHING", callback_data='confirm_delete_all')],
                [InlineKeyboardButton("❌ Cancel", callback_data='cancel_delete_all')],
            ]
            await query.edit_message_text(
                text="⚠️ *Are you absolutely sure you want to delete ALL your data?*\n\nThis action *cannot be undone!*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

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

    # Priority: check for a pending settings input before doing expense parsing
    awaiting = context.user_data.get('awaiting_setting')
    if awaiting:
        await _handle_setting_input(update, context, awaiting)
        return

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
                type_icon = "🟢" if status == 'success' and expense_data.get('type') == 'income' else "🔴"
                word = "Income" if type_icon == "🟢" else "Expense"
                
                response_text = (
                    f"✅ *{word} Saved!*\n\n"
                    f"💰 Amount: {type_icon} *₪{amount:.2f}*\n"
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

                # === Budget / Goal Smart Notification ===
                if expense_data.get('type') == 'income':
                    profile = await asyncio.to_thread(db.get_profile, telegram_id)
                    goal = profile.get('additional_info') if profile else None
                    if goal:
                        response_text += f"\n🎯 *Progress!* You're one step closer to: _{_escape_markdown(goal)}_"
                else:
                    budget = await asyncio.to_thread(db.get_budget, user_id)
                    if budget:
                        spent_this_month, _ = await asyncio.to_thread(db.get_monthly_summary, user_id)
                        pct = (spent_this_month / budget) * 100
                        
                        bar_len = 10
                        filled = min(bar_len, int((pct / 100) * bar_len))
                        bar = "▮" * filled + "▯" * (bar_len - filled)
                        
                        response_text += f"\n📊 *Budget:* [{bar}] {pct:.0f}%\n"

                        if pct >= 100:
                            response_text += "🚨 *Warning: You have exceeded your monthly budget!*"
                        elif pct >= 80:
                            response_text += "⚠️ *Careful: You have used over 80% of your budget.*"
            else:
                response_text = "⚠️ *Error*: Could not extract amount or category."

        elif status == 'no_category':
            # We found a number but couldn't figure out the exact category map. Prompt with a keyboard!
            amt = expense_data.get('amount')
            desc = expense_data.get('text', user_text)  # the raw extracted string or full text
            
            if amt:
                # Save pending state
                context.user_data['pending_expense'] = {"amount": float(amt), "description": desc}
                
                response_text = f"🔢 Got *₪{amt:.2f}*.\n\nPlease pick a category for _{_escape_markdown(desc)}_:"
                reply_markup = _get_category_keyboard()
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
        
    reply_markup = None
    if status == 'success' and expense_data.get('amount') and expense_data.get('category'):
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ Undo", callback_data='undo_last'), InlineKeyboardButton("📊 Dashboard", callback_data='back_to_menu')]
        ])

    await _safe_send(context.bot, chat_id, response_text, reply_markup=reply_markup)


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

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('menu', menu_command))
    application.add_handler(CommandHandler('dashboard', dashboard_command))
    application.add_handler(CommandHandler('settings', settings_command))
    application.add_handler(CommandHandler('undo', undo_command))
    application.add_handler(CommandHandler('budget', budget_command))
    application.add_handler(CommandHandler('export', export_command))
    application.add_handler(CommandHandler('deleteall', deleteall_command))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # ── Post-Initialization: Persistent Keyboard Menu Button ──
    async def post_init(application):
        from telegram import MenuButtonWebApp, WebAppInfo
        webapp_url = os.getenv("WEBAPP_URL", "http://localhost:8000/webapp")
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📊 Dashboard",
                web_app=WebAppInfo(url=webapp_url)
            )
        )
        logger.info(f"Persistent WebApp Menu Button configured: {webapp_url}")

    application.post_init = post_init

    return application


if __name__ == '__main__':
    # Standard Polling startup (for local development)
    db.init_db()
    app = get_application()
    if app:
        logger.info("Bot is starting (Polling)...")
        app.run_polling(drop_pending_updates=True)

