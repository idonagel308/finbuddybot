import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    CallbackQueryHandler, filters, ContextTypes
)

from core.config import logger
import services.database as db
from handlers.utils import _safe_send

from handlers.commands import (
    start, help_command, menu_command, dashboard_command,
    undo_command, budget_command, export_command, deleteall_command
)
from handlers.settings_ui import settings_command
from handlers.callbacks import button_handler
from handlers.messages import handle_message

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
