import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

from database.user_management import set_profile, get_profile, set_budget
from handlers.utils import _safe_send, _private_only, _invalidate_profile_cache
from handlers.settings_ui import _profile_defaults

@_private_only
async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, is_restart: bool = False):
    """Entry point for onboarding, sends welcome and Language selection."""
    chat_id = update.effective_chat.id
    
    if is_restart:
        text = "🔄 *Onboarding Restarted*\n\nLet's set up your profile from scratch.\n\n"
    else:
        text = "🏦 *Welcome to FinTechBot Premium.*\n\nI am your Personal Wealth Manager.\n\n"
        
    text += "🌐 *First, please choose your language:*\n_All insights will be in this language._"
    
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
        text=f"✅ Language set to {lang_name}.\n\n💱 *Now, choose your primary currency:*",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def onboard_cur_handler(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, data: str):
    cur_name = data.split('_')[2]
    profile = await get_profile(telegram_id)
    p = _profile_defaults(profile)
    await set_profile(telegram_id, p['age'], p['yearly_income'], cur_name, p['language'], p['additional_info'], p['account_type'])
    _invalidate_profile_cache(telegram_id)
    
    keyboard = [
        [InlineKeyboardButton("👤 Personal (Default)", callback_data='onboard_acct_personal')],
        [InlineKeyboardButton("💼 Small Business", callback_data='onboard_acct_business')],
    ]
    await query.edit_message_text(
        text=f"✅ Currency set to {cur_name}.\n\n🛠 *What type of account do you need?*\n\n_Small Business enables future tracking and cash flow forecasting._",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def onboard_account_handler(query, telegram_id: int, context: ContextTypes.DEFAULT_TYPE, data: str):
    acct_type = data.split('_')[2]
    profile = await get_profile(telegram_id)
    p = _profile_defaults(profile)
    await set_profile(telegram_id, p['age'], p['yearly_income'], p['currency'], p['language'], p['additional_info'], acct_type)
    _invalidate_profile_cache(telegram_id)
    
    context.user_data['awaiting_onboard_budget'] = True
    await query.edit_message_text(
        text=f"✅ Account type set to {acct_type.title()}.\n\n💰 *Finally, type your monthly budget amount:*\n_(e.g., 5000)_",
        parse_mode='Markdown'
    )

async def handle_onboard_budget_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    context.user_data.pop('awaiting_onboard_budget', None)
    
    try:
        amount = float(text.replace(',', '').replace(' ', ''))
        if amount <= 0 or amount > 100000000:
            raise ValueError()
        await set_budget(user_id, amount)
        
        webapp_url = os.getenv("WEBAPP_URL", "http://localhost:8000/webapp")
        from telegram import ReplyKeyboardMarkup, KeyboardButton
        reply_keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(text="🌐 Open Web Dashboard", web_app=WebAppInfo(url=webapp_url))]],
            resize_keyboard=True,
            persistent=True
        )
        
        await _safe_send(context.bot, chat_id, "A persistent Web Dashboard button has been added to your screen below! 👇", reply_markup=reply_keyboard)
        
        # Show proper menu based on account choice
        from handlers.commands import _get_main_menu_keyboard
        profile = await _get_cached_profile(user_id)
        is_business = (profile.get('account_type') == 'business') if profile else False
        
        await _safe_send(context.bot, chat_id, f"✅ *Setup Complete!*\nMonthly budget set to {amount:,.0f}.\n\nYou can now start logging expenses or open your dashboard below.", reply_markup=_get_main_menu_keyboard(is_business=is_business), parse_mode='Markdown')
        
    except ValueError:
        context.user_data['awaiting_onboard_budget'] = True
        await _safe_send(context.bot, chat_id, "⚠️ Invalid input. Please type a positive number for your budget (e.g. 5000):", parse_mode='Markdown')
        return True
    
    return True
