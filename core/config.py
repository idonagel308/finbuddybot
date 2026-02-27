import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure global logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Suppress httpx logs that leak the bot token in URLs
logging.getLogger("httpx").setLevel(logging.WARNING)

# --- Constraints & Rate Limits ---
MAX_MESSAGES_PER_MINUTE = 10
MAX_MESSAGE_LENGTH = 500
TELEGRAM_MAX_LENGTH = 4096  # Telegram's hard limit for a single message

# --- Single-tenant Security ---
ALLOWED_USER_ID = os.getenv('ALLOWED_USER_ID')
if ALLOWED_USER_ID:
    try:
        ALLOWED_USER_ID = int(ALLOWED_USER_ID)
    except ValueError:
        logger.error(f"Invalid ALLOWED_USER_ID in .env: {ALLOWED_USER_ID}. Must be an integer.")
        ALLOWED_USER_ID = None

# --- UI & Interaction Constants ---
# Whitelist of valid callback data values
VALID_CALLBACKS = {
    'last_expenses', 'monthly_list', 'this_month', 'year_overview', 'pie_chart',
    'insights', 'delete_all_monthly', 'back_to_menu', 'settings_menu', 'settings_tools',
    'export_csv', 'delete_all', 'undo_last',
    # Settings sub-menus
    'settings_set_lang', 'settings_set_currency', 'settings_set_budget',
    'settings_set_age', 'settings_set_income', 'settings_set_goals',
    'settings_edit_lang_custom', 'settings_edit_currency_custom',
}

# ── Emoji Display Mapping ──
# The data layer stores clean strings ('Food', 'Transport').
# This mapping adds emojis for the Telegram UI only.
CATEGORY_EMOJIS = {
    'Housing': '🏠', 'Food': '🍔', 'Transport': '🚗',
    'Entertainment': '🎉', 'Shopping': '🛍️', 'Health': '❤️',
    'Education': '📚', 'Financial': '💸', 'Other': '❓',
    'Salary': '💼', 'Investment': '📈', 'Gift': '🎁',
}
