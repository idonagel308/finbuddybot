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
