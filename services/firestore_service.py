import logging
from datetime import datetime
from google.cloud import firestore

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Firestore client (AsyncClient)
# ADC (Application Default Credentials) will be used automatically in Cloud Run
db = firestore.AsyncClient()

async def add_expense(user_id: int, amount: float, category: str, description: str = "", transaction_type: str = "expense"):
    """
    Adds a new expense or income to Firestore.
    Path: users/{user_id}/expenses/{auto_id}
    """
    if category in {'Salary', 'Investment', 'Gift'} and transaction_type == "expense":
        transaction_type = "income"

    user_id_str = str(user_id)
    doc_ref = db.collection("users").document(user_id_str).collection("expenses").document()
    
    data = {
        "amount": amount,
        "category": category,
        "description": description,
        "type": transaction_type,
        "timestamp": firestore.SERVER_TIMESTAMP,
        "date": datetime.now().isoformat() # Optional: keeping string format for easy reading too
    }
    
    try:
        await doc_ref.set(data)
        logger.info(f"Added {transaction_type} to Firestore for user {user_id}")
        return doc_ref.id
    except Exception as e:
        logger.error(f"Error adding {transaction_type} to Firestore: {e}")
        raise

async def get_monthly_summary(user_id: int, year: int = None, month: int = None):
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
    
    # Query for the month
    try:
        # Note: Firestore inequality queries on multiple fields (timestamp) might need composite indexes.
        # We query by the `date` string field which is easier without composite index configs initially.
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

# ── Profile Management ──

async def set_profile(user_id: int, age: int, yearly_income: float, currency: str = 'NIS', language: str = 'English', additional_info: str = ""):
    """Sets/updates profile in Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    data = {
        "profile": {
            "age": age,
            "yearly_income": yearly_income,
            "currency": currency,
            "language": language,
            "additional_info": additional_info,
            "updated_at": firestore.SERVER_TIMESTAMP
        }
    }
    
    try:
        await user_ref.set(data, merge=True)
        logger.info(f"Updated profile for user {user_id} in Firestore")
    except Exception as e:
        logger.error(f"Error setting profile for user {user_id}: {e}")
        raise

async def get_profile(user_id: int):
    """Retrieves profile from Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    try:
        doc = await user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("profile")
        return None
    except Exception as e:
        logger.error(f"Error fetching profile for user {user_id}: {e}")
        return None

# ── Budget Management ──

async def set_budget(user_id: int, amount: float):
    """Sets/updates budget in Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    data = {
        "budget": {
            "amount": amount,
            "updated_at": firestore.SERVER_TIMESTAMP
        }
    }
    
    try:
        await user_ref.set(data, merge=True)
        logger.info(f"Updated budget for user {user_id} in Firestore")
    except Exception as e:
        logger.error(f"Error setting budget for user {user_id}: {e}")
        raise

async def get_budget(user_id: int):
    """Retrieves budget from Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    try:
        doc = await user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            budget = data.get("budget")
            return budget.get("amount") if budget else None
        return None
    except Exception as e:
        logger.error(f"Error fetching budget for user {user_id}: {e}")
        return None

# ── Settings Management ──

async def save_user_settings(user_id: int, theme: str = None, layout: str = None, budget_target: float = None, financial_goal: str = None, language: str = None, accent_color: str = None):
    """Saves or updates user-specific dashboard preferences in Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    settings_data = {
        "theme": theme,
        "layout": layout,
        "budget_target": budget_target,
        "financial_goal": financial_goal,
        "language": language,
        "accent_color": accent_color,
        "updated_at": firestore.SERVER_TIMESTAMP
    }
    
    # Filter out None values to avoid overwriting with null if using merge
    filtered_settings = {k: v for k, v in settings_data.items() if v is not None}
    
    data = {"settings": filtered_settings}
    
    try:
        await user_ref.set(data, merge=True)
        logger.info(f"Updated settings for user {user_id} in Firestore")
    except Exception as e:
        logger.error(f"Error saving settings for user {user_id}: {e}")
        raise

async def get_user_settings(user_id: int) -> dict:
    """Retrieves user settings from Firestore."""
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    
    try:
        doc = await user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get("settings", {})
        return {}
    except Exception as e:
        logger.error(f"Error fetching settings for user {user_id}: {e}")
        return {}

# ── Retrieval Management ──

async def get_recent_expenses(user_id: int, limit: int = 5):
    """Retrieves most recent expenses from Firestore."""
    user_id_str = str(user_id)
    expenses_ref = db.collection("users").document(user_id_str).collection("expenses")
    
    try:
        query = expenses_ref.order_by("date", direction=firestore.Query.DESCENDING).limit(limit)
        docs = query.stream()
        
        results = []
        async for doc in docs:
            data = doc.to_dict()
            # Format to match the tuple structure expected by legacy handlers if needed, 
            # or just return dicts. We'll return tuples to minimize handler changes.
            # (id, date, amount, category, description, type)
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

async def get_monthly_expenses(user_id: int, year: int = None, month: int = None):
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
        return []

async def get_daily_aggregation(user_id: int, year: int = None, month: int = None):
    """Calculates daily spent totals for a month for the dashboard chart."""
    expenses = await get_monthly_expenses(user_id, year, month)
    
    daily_totals = {}
    for _, date_str, amount, _, _, tx_type in expenses:
        if tx_type == 'expense':
            try:
                # ISO format '2026-03-02T...' -> '2026-03-02'
                day = date_str.split('T')[0]
                daily_totals[day] = daily_totals.get(day, 0.0) + float(amount)
            except:
                continue
    
    # Sort by date
    sorted_days = sorted(daily_totals.keys())
    return [{"date": day, "spent": daily_totals[day]} for day in sorted_days]
