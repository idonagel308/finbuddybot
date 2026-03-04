from typing import Optional, Dict, Any
from google.cloud import firestore
from database import db, logger
from database.exceptions import ProfileError

async def set_profile(user_id: int, age: int, yearly_income: float, currency: str = 'NIS', language: str = 'English', additional_info: str = "", account_type: str = "personal") -> None:
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
            "account_type": account_type,
            "updated_at": firestore.SERVER_TIMESTAMP
        }
    }
    
    try:
        await user_ref.set(data, merge=True)
        logger.info(f"Updated profile for user {user_id} in Firestore")
    except Exception as e:
        logger.error(f"Error setting profile for user {user_id}: {e}")
        raise ProfileError(f"Failed to set profile: {e}")

async def get_profile(user_id: int) -> Optional[Dict[str, Any]]:
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

async def set_budget(user_id: int, amount: float) -> None:
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
        raise ProfileError(f"Failed to set budget: {e}")

async def get_budget(user_id: int) -> Optional[float]:
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

async def save_user_settings(user_id: int, theme: Optional[str] = None, layout: Optional[str] = None, budget_target: Optional[float] = None, financial_goal: Optional[str] = None, language: Optional[str] = None, accent_color: Optional[str] = None) -> None:
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
        raise ProfileError(f"Failed to save settings: {e}")

async def get_user_settings(user_id: int) -> Dict[str, Any]:
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

async def reset_user_data(user_id: int) -> bool:
    """Deletes ALL data for a user (profile, budget, settings).
    Expenses are stored in a sub-collection and must be deleted separately.
    Returns True on success, False on failure.
    """
    user_id_str = str(user_id)
    user_ref = db.collection("users").document(user_id_str)
    try:
        await user_ref.delete()
        logger.info(f"Deleted full user document for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error resetting data for user {user_id}: {e}")
        return False
