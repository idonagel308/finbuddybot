import time
import asyncio
from functools import wraps
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import services.database as db
import services.llm_helper as llm_helper
from core.config import logger, MAX_MESSAGES_PER_MINUTE, TELEGRAM_MAX_LENGTH, ALLOWED_USER_ID, CATEGORY_EMOJIS

_user_message_timestamps = defaultdict(list)

def _display_category(category: str) -> str:
    """Convert a clean category string to an emoji-decorated display string."""
    emoji = CATEGORY_EMOJIS.get(category, '❓')
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
