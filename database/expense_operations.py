from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from google.cloud import firestore
from database import db, logger
from database.exceptions import ExpenseError
import asyncio


async def add_expense(user_id: int, amount: float, category: str, description: str = "", transaction_type: str = "expense", status: str = "completed", due_date: Optional[str] = None) -> str:
    """
    Adds a new expense or income to Firestore.
    Path: users/{user_id}/expenses/{auto_id}
    """
    if category in {'Salary', 'Investment', 'Gift'} and transaction_type == "expense":
        transaction_type = "income"

    user_id_str = str(user_id)
    data = {
        "amount": amount,
        "category": category,
        "description": description,
        "type": transaction_type,
        "status": status,
        "due_date": due_date,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "date": datetime.now().isoformat()
    }
    
    try:
        doc_ref = db.collection("users").document(user_id_str).collection("expenses").document()
        await doc_ref.set(data)
        logger.info(f"Added {transaction_type} to Firestore for user {user_id}")
        
            
        return doc_ref.id
    except Exception as e:
        logger.error(f"Error adding {transaction_type} to Firestore: {e}")
        raise ExpenseError(f"Failed to add {transaction_type}: {e}")

async def delete_expense(user_id: int, expense_id: str) -> bool:
    """Deletes a specific expense by ID."""
    user_id_str = str(user_id)
    try:
        doc_ref = db.collection("users").document(user_id_str).collection("expenses").document(str(expense_id))
        await doc_ref.delete()
        return True
    except Exception as e:
        logger.error(f"Error deleting expense {expense_id}: {e}")
        return False

async def delete_all_expenses(user_id: int) -> int:
    """Deletes all expenses for a user and returns the count."""
    user_id_str = str(user_id)
    try:
        expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
        docs = expenses_ref.stream()
        count = 0
        async for doc in docs:
            await doc.reference.delete()
            count += 1
        return count
    except Exception as e:
        logger.error(f"Error deleting all expenses: {e}")
        return 0

async def delete_monthly_expenses(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> int:
    """Deletes all expenses for a specific month and returns the count."""
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    
    start_date = datetime(y, m, 1)
    if m == 12:
        end_date = datetime(y + 1, 1, 1)
    else:
        end_date = datetime(y, m + 1, 1)

    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()

    user_id_str = str(user_id)
    try:
        expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
        query = expenses_ref.where("date", ">=", start_iso).where("date", "<", end_iso)
        docs = query.stream()
        count = 0
        async for doc in docs:
            await doc.reference.delete()
            count += 1
        return count
    except Exception as e:
        logger.error(f"Error deleting monthly expenses: {e}")
        return 0

async def get_last_expense_id(user_id: int) -> Optional[str]:
    """Retrieves the ID of the most recent expense."""
    from database.queries import get_recent_expenses
    recent = await get_recent_expenses(user_id, limit=1)
    if recent:
        return recent[0][0]
    return None
