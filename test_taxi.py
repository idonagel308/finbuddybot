import asyncio
import traceback
from telegram import Update, Message, Chat, User
from telegram.ext import ContextTypes
import services.llm_helper as llm_helper
from handlers.messages import handle_message
from unittest.mock import AsyncMock, MagicMock

async def test_taxi():
    # Mock update
    update = MagicMock(spec=Update)
    update.message = MagicMock(spec=Message)
    update.message.text = "taxi 50"
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = 12345
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345

    # Mock context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    context.bot = AsyncMock()
    context.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))
    context.bot.delete_message = AsyncMock()

    # Call it and catch the exception inside our own try/except
    try:
        await handle_message(update, context)
        print("MOCKED RESPONSE:")
        print(context.bot.send_message.call_args_list)
    except Exception as e:
        print("EXCEPTION CAUGHT BY SCRIPT:", e)
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_taxi())
