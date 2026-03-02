import asyncio
from datetime import datetime
from database import db, logger
from core.bot_setup import get_application

def _is_due_soon(due_date_str: str) -> bool:
    try:
        due = datetime.strptime(due_date_str[:10], "%Y-%m-%d").date()
        now = datetime.now().date()
        return 0 <= (due - now).days <= 1
    except Exception:
        return False

async def payment_reminder_job():
    logger.info("Proactive payment reminder job started.")
    while True:
        try:
            users_ref = db.collection("users")
            users = users_ref.stream()
            app = get_application()
            if not app or not app.bot:
                logger.warning("Bot application not fully initialized, skipping reminder check.")
            else:
                async for user_doc in users:
                    user_id = user_doc.id
                    expenses_ref = user_doc.reference.collection("expenses")
                    
                    # Look for planned expenses
                    query = expenses_ref.where("status", "==", "planned")
                    planned_docs = query.stream()
                    
                    async for planned_doc in planned_docs:
                        data = planned_doc.to_dict()
                        
                        if data.get("reminded"):
                            continue
                            
                        due_date = data.get("due_date")
                        if due_date and _is_due_soon(due_date):
                            amount = data.get("amount")
                            cat = data.get("category")
                            desc = data.get("description", "")
                            
                            msg = f"🔔 *Payment Reminder*\nYou have a planned payment coming up:\n\n💰 Amount: ₪{amount}\n📂 Category: {cat}\n📝 Details: {desc}\n📆 Due: {due_date[:10]}"
                            
                            try:
                                await app.bot.send_message(chat_id=int(user_id), text=msg, parse_mode="Markdown")
                                await planned_doc.reference.update({"reminded": True})
                                logger.info(f"Reminded user {user_id} about planned payment {planned_doc.id}")
                            except Exception as e:
                                logger.error(f"Failed to remind user {user_id}: {e}")
                                
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}")
            
        # Check every 6 hours
        await asyncio.sleep(6 * 3600)
