import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

from database.user_management import set_profile, get_profile, set_budget
from handlers.utils import _safe_send, _private_only, _invalidate_profile_cache, _get_cached_profile
from handlers.settings_ui import _profile_defaults
from services.localization import t


@_private_only
async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, is_restart: bool = False):
    """Entry point for onboarding, sends welcome and Language selection."""
    chat_id = update.effective_chat.id

    if is_restart:
        text = t("welcome_restart", "English")
    else:
        text = t("welcome_new", "English")

    text += t("choose_language", "English")

    keyboard = [
        [InlineKeyboardButton("🇬🇧 English", callback_data='onboard_lang_English'),
         InlineKeyboardButton("🇮🇱 Hebrew", callback_data='onboard_lang_Hebrew')],
        [InlineKeyboardButton("🇪🇸 Spanish", callback_data='onboard_lang_Spanish'),
         InlineKeyboardButton("🇫🇷 French", callback_data='onboard_lang_French')],
    ]
    await _safe_send(context.bot, chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def onboard_lang_handler(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, data: str):
    lang_name = data.split('_')[2]
    profile = await get_profile(telegram_id)
    p = _profile_defaults(profile)
    await set_profile(telegram_id, p['age'], p['yearly_income'], p['currency'], lang_name, p['additional_info'], p['account_type'])
    _invalidate_profile_cache(telegram_id)

    keyboard = [
        [InlineKeyboardButton("🇮🇱 NIS ₪", callback_data='onboard_cur_NIS'),
         InlineKeyboardButton("🇺🇸 USD $", callback_data='onboard_cur_USD')],
        [InlineKeyboardButton("🇪🇺 EUR €", callback_data='onboard_cur_EUR'),
         InlineKeyboardButton("🇬🇧 GBP £", callback_data='onboard_cur_GBP')],
    ]
    await query.edit_message_text(
        text=t("lang_set", lang_name),
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def onboard_cur_handler(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, data: str):
    cur_name = data.split('_')[2]
    profile = await get_profile(telegram_id)
    p = _profile_defaults(profile)
    await set_profile(telegram_id, p['age'], p['yearly_income'], cur_name, p['language'], p['additional_info'], p['account_type'])
    _invalidate_profile_cache(telegram_id)

    lang = p['language']
    keyboard = [
        [InlineKeyboardButton("👤 Personal" if lang == "English" else "👤 אישי" if lang == "Hebrew" else "👤 Personal" if lang == "Spanish" else "👤 Personnel", callback_data='onboard_acct_personal')],
        [InlineKeyboardButton("💼 Small Business" if lang == "English" else "💼 עסק קטן" if lang == "Hebrew" else "💼 Pequeña Empresa" if lang == "Spanish" else "💼 Petite Entreprise", callback_data='onboard_acct_business')],
    ]
    await query.edit_message_text(
        text=t("currency_set", lang, cur=cur_name),
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def onboard_account_handler(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, data: str):
    acct_type = data.split('_')[2]
    profile = await get_profile(telegram_id)
    p = _profile_defaults(profile)
    await set_profile(telegram_id, p['age'], p['yearly_income'], p['currency'], p['language'], p['additional_info'], acct_type)
    _invalidate_profile_cache(telegram_id)

    lang = p['language']
    context.user_data['awaiting_onboard_budget'] = True
    await query.edit_message_text(
        text=t("account_set_budget_prompt", lang, acct=acct_type.title()),
        parse_mode='Markdown'
    )


async def handle_onboard_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    context.user_data.pop('awaiting_onboard_budget', None)

    # Get language for localized responses
    profile = await _get_cached_profile(user_id)
    lang = (profile.get('language') or 'English') if profile else 'English'

    try:
        amount = float(text.replace(',', '').replace(' ', ''))
        if amount <= 0 or amount > 100000000:
            raise ValueError()
        await set_budget(user_id, amount)

        webapp_url = os.getenv("WEBAPP_URL", "http://localhost:8000/webapp")
        reply_keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(text="🌐 Open Web Dashboard", web_app=WebAppInfo(url=webapp_url))]],
            resize_keyboard=True,
            is_persistent=True
        )

        await _safe_send(context.bot, chat_id, t("web_dashboard_added", lang), reply_markup=reply_keyboard)

        # Show proper menu based on account choice
        from handlers.commands import _get_main_menu_keyboard
        # Re-fetch profile now that budget is set and cache is fresh
        profile = await get_profile(user_id)
        is_business = (profile.get('account_type') == 'business') if profile else False

        await _safe_send(
            context.bot, chat_id,
            t("setup_complete", lang, amount=f"{amount:,.0f}"),
            reply_markup=_get_main_menu_keyboard(is_business=is_business, language=lang),
            parse_mode='Markdown'
        )

    except ValueError:
        context.user_data['awaiting_onboard_budget'] = True
        await _safe_send(context.bot, chat_id, t("budget_invalid", lang), parse_mode='Markdown')
        return True

    return True
