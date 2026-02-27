import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import services.database as db
from handlers.utils import _safe_send, _private_only, _invalidate_profile_cache


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
