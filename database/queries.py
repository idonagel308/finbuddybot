from typing import Optional, List, Tuple
from datetime import datetime
from google.cloud import firestore
from database import db, logger

async def get_monthly_summary(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> Tuple[float, float]:
    """
    Calculates total expenses and income for a month using Firestore queries.
    Returns (total_expenses, total_income)
    """
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
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        query = expenses_ref.where("date", ">=", start_iso).where("date", "<", end_iso)
        docs = query.stream()
        
        total_exp = 0.0
        total_inc = 0.0
        
        async for doc in docs:
            data = doc.to_dict()
            amt = float(data.get("amount", 0))
            if data.get("type", "expense") == "income":
                total_inc += amt
            else:
                total_exp += amt
                
        return total_exp, total_inc
    except Exception as e:
        logger.error(f"Error fetching monthly summary from Firestore for user {user_id}: {e}")
        return 0.0, 0.0

async def get_recent_expenses(user_id: int, limit: int = 5) -> List[Tuple]:
    """Retrieves most recent expenses from Firestore."""
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        query = expenses_ref.order_by("date", direction=firestore.Query.DESCENDING).limit(limit)
        docs = query.stream()
        
        results = []
        async for doc in docs:
            data = doc.to_dict()
            results.append((
                doc.id,
                data.get("date"),
                data.get("amount"),
                data.get("category"),
                data.get("description"),
                data.get("type", "expense")
            ))
        return results
    except Exception as e:
        logger.error(f"Error fetching recent expenses from Firestore: {e}")
        return []

async def get_monthly_expenses(user_id: int, year: Optional[int] = None, month: Optional[int] = None) -> List[Tuple]:
    """Retrieves all expenses for a specific month from Firestore."""
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
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        query = expenses_ref.where("date", ">=", start_iso).where("date", "<", end_iso).order_by("date", direction=firestore.Query.DESCENDING)
        docs = query.stream()
        
        results = []
        async for doc in docs:
            data = doc.to_dict()
            results.append((
                doc.id,
                data.get("date"),
                data.get("amount"),
                data.get("category"),
                data.get("description"),
                data.get("type", "expense")
            ))
        return results
    except Exception as e:
        logger.error(f"Error fetching monthly expenses from Firestore: {e}")

async def get_pending_payments(user_id: int) -> List[Tuple]:
    """Retrieves all planned/pending payments from Firestore."""
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        # Query for status == "planned"
        query = expenses_ref.where("status", "==", "planned").order_by("date", direction=firestore.Query.DESCENDING)
        docs = query.stream()
        
        results = []
        async for doc in docs:
            data = doc.to_dict()
            results.append((
                doc.id,
                data.get("date"),
                data.get("amount"),
                data.get("category"),
                data.get("description"),
                data.get("type", "expense"),
                data.get("due_date")
            ))
        return results
    except Exception as e:
        logger.error(f"Error fetching pending payments from Firestore: {e}")
        return []
