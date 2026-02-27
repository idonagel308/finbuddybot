import os
import io
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

import services.database as db
from handlers.utils import _safe_send, _private_only


def _get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Returns the primary dashboard inline keyboard."""
    
    # URL of your mounted FastAPI static webapp (can be configurable via .env in production)
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
        except IndexError:
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
