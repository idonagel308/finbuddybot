import os
import re
import json
import time
import logging
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure logging (replace print statements)
logger = logging.getLogger(__name__)

# Configure Gemini API
api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    logger.warning("GOOGLE_API_KEY not found in .env")
else:
    genai.configure(api_key=api_key)

# List of models to try in order of preference/stability
MODELS_TO_TRY = [
    "gemini-2.5-flash",       # Primary - confirmed working
    "gemini-2.0-flash-lite",  # Fallback
]

# Cache GenerativeModel instances to avoid recreating on every call
_model_cache = {}

# Allowed categories for validation
ALLOWED_CATEGORIES = {
    '🏠 Housing', '🍔 Food', '🚗 Transport', '🎉 Entertainment',
    '🛍️ Shopping', '❤️ Health', '📚 Education', '💸 Financial', '❓ Other'
}

# Input limits
MAX_INPUT_LENGTH = 500
MAX_AMOUNT = 1_000_000


def _sanitize_user_input(text: str) -> str:
    """
    Sanitizes user input before embedding in LLM prompts.
    Prevents prompt injection attacks.
    """
    if not text or not isinstance(text, str):
        return ""

    # Truncate to max length
    text = text[:MAX_INPUT_LENGTH]

    # Remove characters that could be used for prompt injection
    # Strip markdown-like formatting, backticks, and control chars
    text = re.sub(r'[`{}[\]\\]', '', text)

    # Remove any "system:", "assistant:", "user:" prefixes that could
    # trick the model into thinking it's a different role
    text = re.sub(r'(?i)(system|assistant|user|ignore|forget|override)\s*:', '', text)

    return text.strip()


def _validate_parsed_expense(data: dict) -> dict:
    """
    Validates the LLM-parsed expense data before returning it.
    Ensures the model didn't hallucinate invalid values.
    """
    if not isinstance(data, dict):
        return None

    amount = data.get('amount')
    category = data.get('category')
    description = data.get('description', '')

    # Validate amount
    if not isinstance(amount, (int, float)) or amount <= 0 or amount > MAX_AMOUNT:
        return None

    # Validate category - must be from allowed set
    if category not in ALLOWED_CATEGORIES:
        # Try to find the closest match
        category = _fuzzy_match_category(category)

    # Sanitize description
    if description:
        description = str(description)[:200].strip()
    else:
        description = ""

    return {
        'amount': float(amount),
        'category': category,
        'description': description
    }


def _fuzzy_match_category(raw_category: str) -> str:
    """Attempts to match a raw category string to an allowed category."""
    if not raw_category:
        return '❓ Other'
    raw_lower = raw_category.lower()
    for allowed in ALLOWED_CATEGORIES:
        # Check if the text part (after emoji) matches
        text_part = allowed.split(' ', 1)[1].lower() if ' ' in allowed else allowed.lower()
        if text_part in raw_lower or raw_lower in text_part:
            return allowed
    return '❓ Other'


def generate_insights(summary_text):
    """
    Generates financial advice based on the provided summary text.
    """
    if not api_key:
        return "⚠️ API Key missing. Cannot generate insights."

    # Sanitize the summary text too
    safe_summary = _sanitize_user_input(summary_text)



    prompt = f"""
    You are a financial advisor. Here is a summary of the user's spending this month:
    {safe_summary}
    
    Provide 3 short, actionable bullet points of advice or observation. 
    Keep it under 50 words total. Be encouraging but realistic.
    Do NOT use any special formatting or markdown. Plain text only.
    """

    for model_name in MODELS_TO_TRY:
        try:
            if model_name not in _model_cache:
                _model_cache[model_name] = genai.GenerativeModel(model_name)
            response = _model_cache[model_name].generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.warning(f"generate_insights: {model_name} failed: {type(e).__name__}")
            continue

    return "Keep tracking your expenses to see where you can save!"


def parse_expense(text):
    """
    Uses Gemini to extract expense details, with retries and model fallbacks.

    Args:
        text (str): The user's message, e.g., "Spent 50 shekels on pizza"

    Returns:
        dict: A dictionary with keys 'amount', 'category', 'description'
              or None if parsing fails after all attempts.
    """
    # Sanitize input BEFORE sending to LLM
    safe_text = _sanitize_user_input(text)
    if not safe_text:
        return None

    # --- Try LLM First ---
    if api_key:
        prompt = f"""
        You are a financial assistant. Extract the following details from this text: "{safe_text}"
        
        Return ONLY a raw JSON object (no markdown, no backticks) with these keys:
        - amount (number, required)
        - category (string, MUST be one of the following exact strings):
            - '🏠 Housing' (Rent, Utilities, Internet, Maintenance)
            - '🍔 Food' (Groceries, Restaurants, Snacks, Coffee)
            - '🚗 Transport' (Fuel, Taxi, Public Transport, Car)
            - '🎉 Entertainment' (Movies, Games, Hobbies, Vacations, Eating Out if leisure)
            - '🛍️ Shopping' (Clothing, Electronics, Furniture, Gadgets)
            - '❤️ Health' (Doctor, Gym, Pharmacy, Personal Care)
            - '📚 Education' (Books, Courses, Tuition)
            - '💸 Financial' (Investments, Savings, Debt, Taxes, Fees)
            - '❓ Other' (Anything else)
        - description (string, the item bought or context)
        
        If the text is not an expense, return null.
        """

        for model_name in MODELS_TO_TRY:
            try:
                if model_name not in _model_cache:
                    _model_cache[model_name] = genai.GenerativeModel(model_name)
                response = _model_cache[model_name].generate_content(prompt)

                content = response.text.strip()
                # Clean up markdown if present
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                data = json.loads(content)

                # Validate the parsed data before returning
                validated = _validate_parsed_expense(data)
                if validated:
                    return validated
                else:
                    logger.warning(f"LLM returned invalid expense data: skipping")
                    break  # Try regex fallback

            except Exception as e:
                error_str = str(e)
                logger.warning(f"parse_expense: {model_name}: {type(e).__name__}")
                if "429" in error_str or "exhausted" in error_str.lower():
                    time.sleep(1)
                continue

    logger.info("LLM unavailable. Falling back to Regex.")

    # --- Regex Fallback ---
    text_lower = safe_text.lower()

    # Pattern 1: Amount then Category (e.g., "50 on food", "spent 20 for taxi")
    match1 = re.search(r'(\d+(?:\.\d+)?)\s*(?:shekels|nis|dollars|euros|k|m)?\s*(?:on|for)?\s*([a-z\s]+)', text_lower)
    if match1:
        amount = float(match1.group(1))
        if amount <= 0 or amount > MAX_AMOUNT:
            return None
        raw_category = match1.group(2).strip()
        category = raw_category.replace('on ', '').replace('for ', '').strip()

        if category.startswith("spent"):
            return None

        return {
            "amount": amount,
            "category": _map_category(category),
            "description": "Via Regex Fallback"
        }

    # Pattern 2: Category then Amount (e.g., "taxi 20", "food 50")
    match2 = re.search(r'([a-z\s]+)\s*(\d+(?:\.\d+)?)', text_lower)
    if match2:
        category = match2.group(1).strip()
        amount = float(match2.group(2))

        if amount <= 0 or amount > MAX_AMOUNT:
            return None

        if "spent" in category:
            category = category.replace("spent", "").strip()

        return {
            "amount": amount,
            "category": _map_category(category),
            "description": "Via Regex Fallback"
        }

    return None


def _map_category(text):
    """Maps a raw text category to the standardized emoji category."""
    text = text.lower()

    mapping = {
        'food': '🍔 Food', 'pizza': '🍔 Food', 'burger': '🍔 Food', 'sushi': '🍔 Food', 'restaurant': '🍔 Food', 'coffee': '🍔 Food', 'groceries': '🍔 Food', 'snack': '🍔 Food',
        'taxi': '🚗 Transport', 'bus': '🚗 Transport', 'train': '🚗 Transport', 'fuel': '🚗 Transport', 'gas': '🚗 Transport', 'flight': '🚗 Transport', 'uber': '🚗 Transport',
        'rent': '🏠 Housing', 'electricity': '🏠 Housing', 'water': '🏠 Housing', 'bill': '🏠 Housing', 'internet': '🏠 Housing',
        'movie': '🎉 Entertainment', 'game': '🎉 Entertainment', 'cinema': '🎉 Entertainment', 'bar': '🎉 Entertainment',
        'clothes': '🛍️ Shopping', 'shoes': '🛍️ Shopping', 'shirt': '🛍️ Shopping', 'shopping': '🛍️ Shopping',
        'gym': '❤️ Health', 'doctor': '❤️ Health', 'pharmacy': '❤️ Health', 'meds': '❤️ Health'
    }

    for key, value in mapping.items():
        if key in text:
            return value

    return '❓ Other'


if __name__ == "__main__":
    # Test the parsing function
    test_text = "Spent 50 shekels on pizza"
    print(f"Testing parsing with: '{test_text}'")
    result = parse_expense(test_text)
    print("Parse Result:", result)

    # Test the insights function
    print("\nTesting insights generation...")
    test_summary = "Food: 150, Transport: 50, Entertainment: 200"
    insight = generate_insights(test_summary)
    print("Insight Result:", insight)
