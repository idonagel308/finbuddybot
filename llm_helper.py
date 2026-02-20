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
    "gemini-2.0-flash",       # Primary - current latest
    "gemini-1.5-flash",       # Fallback - stable
    "gemini-2.0-flash-lite",  # Fallback
]

# Cache GenerativeModel instances to avoid recreating on every call
_model_cache = {}

# Allowed categories for validation (clean strings — no emojis in the data layer)
ALLOWED_CATEGORIES = {
    'Housing', 'Food', 'Transport', 'Entertainment',
    'Shopping', 'Health', 'Education', 'Financial', 'Other'
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

    # Validate category — must be from allowed set
    if category not in ALLOWED_CATEGORIES:
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
        return 'Other'
    raw_lower = raw_category.lower()
    for allowed in ALLOWED_CATEGORIES:
        if allowed.lower() in raw_lower or raw_lower in allowed.lower():
            return allowed
    return 'Other'


def generate_insights(totals, age=None, wage=None, budget=None, recent_expenses=None):
    """
    Generates tailored financial advice based on structured spending data.
    """
    if not api_key:
        return "⚠️ API Key missing. Cannot generate insights."

    # Format context for segments
    totals_str = "\n".join([f"- {cat}: {amount:.2f}" for cat, amount in totals.items()])
    
    profile_context = ""
    if age and wage:
        profile_context = f"- User Profile: {age} years old, earning {wage:.0f} NIS/month\n"
    
    budget_context = ""
    if budget:
        total_spent = sum(totals.values())
        budget_context = f"- Monthly Budget: {budget:.0f} (Currently at {total_spent/budget*100:.0f}%)\n"

    recent_str = ""
    if recent_expenses:
        recent_str = "\nRecent Transactions:\n" + "\n".join([
            f"- {e[1][5:10]}: {e[2]} on {e[3]} ({e[4]})" for e in recent_expenses[:5]
        ])

    prompt = f"""
    You are an elite personal financial coach. Analyze this user's data and provide 3 HIGHLY SPECIFIC, actionable tips.
    
    DATA POINTS:
    {profile_context}{budget_context}
    Breakdown by Category:
    {totals_str}
    {recent_str}
    
    GUIDELINES:
    1. Be concise (max 60 words total).
    2. Identify the biggest spending category or an unusual trend.
    3. If over budget, give a specific saving strategy.
    4. If under budget, encourage them.
    5. Plain text only, NO markdown, NO emojis (I will add them).
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
            - 'Housing' (Rent, Utilities, Internet, Maintenance)
            - 'Food' (Groceries, Restaurants, Snacks, Coffee)
            - 'Transport' (Fuel, Taxi, Public Transport, Car)
            - 'Entertainment' (Movies, Games, Hobbies, Vacations, Eating Out if leisure)
            - 'Shopping' (Clothing, Electronics, Furniture, Gadgets)
            - 'Health' (Doctor, Gym, Pharmacy, Personal Care)
            - 'Education' (Books, Courses, Tuition)
            - 'Financial' (Investments, Savings, Debt, Taxes, Fees)
            - 'Other' (Anything else)
        - description (string, the item bought or context)
        
        If the text is not an expense, return null.
        """

        for model_name in MODELS_TO_TRY:
            try:
                if model_name not in _model_cache:
                    _model_cache[model_name] = genai.GenerativeModel(model_name)
                response = _model_cache[model_name].generate_content(prompt)

                content = response.text.strip()
                
                # Robust JSON extraction: search for the first { and last }
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    content = json_match.group(0)
                
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode JSON from {model_name}: {content[:100]}")
                    continue

                # Validate the parsed data before returning
                validated = _validate_parsed_expense(data)
                if validated:
                    return validated
                else:
                    logger.warning(f"LLM returned invalid expense data: trying next model")
                    continue  # Try next model before fallback to regex if validation failed (hallucination)

            except Exception as e:
                error_str = str(e)
                logger.warning(f"parse_expense: {model_name}: {type(e).__name__}")
                if "429" in error_str or "exhausted" in error_str.lower():
                    time.sleep(1)
                continue

    logger.info("LLM unavailable. Falling back to Regex.")

    # --- Regex Fallback ---
    # Enhanced for Hebrew and international characters
    text_lower = safe_text.lower()

    # Pattern 1: Any number followed by text (e.g. "50 pizza", "30 שקל")
    # Supports Hebrew via \u0590-\u05FF range
    match = re.search(r'(\d+(?:\.\d+)?)\s*([a-zA-Z\u0590-\u05FF\s]+)', text_lower)
    if match:
        amount = float(match.group(1))
        if 0 < amount <= MAX_AMOUNT:
            raw_text = match.group(2).strip()
            # Clean up common noise words
            clean_category = re.sub(r'^(on|for|spent|ב-|שקל|שקלים|nis|shekels)\s*', '', raw_text, flags=re.IGNORECASE)
            return {
                "amount": amount,
                "category": _map_category(clean_category),
                "description": f"Extracted from: {safe_text}"
            }

    # Pattern 2: Text followed by number (e.g. "pizza 50")
    match2 = re.search(r'([a-zA-Z\u0590-\u05FF\s]+)\s*(\d+(?:\.\d+)?)', text_lower)
    if match2:
        raw_text = match2.group(1).strip()
        amount = float(match2.group(2))
        if 0 < amount <= MAX_AMOUNT:
            return {
                "amount": amount,
                "category": _map_category(raw_text),
                "description": f"Extracted from: {safe_text}"
            }

    return None


def _map_category(text):
    """Maps a raw text keyword to a clean category string."""
    text = text.lower()

    mapping = {
        'food': 'Food', 'pizza': 'Food', 'burger': 'Food', 'sushi': 'Food', 'restaurant': 'Food', 'coffee': 'Food', 'groceries': 'Food', 'snack': 'Food',
        'taxi': 'Transport', 'bus': 'Transport', 'train': 'Transport', 'fuel': 'Transport', 'gas': 'Transport', 'flight': 'Transport', 'uber': 'Transport',
        'rent': 'Housing', 'electricity': 'Housing', 'water': 'Housing', 'bill': 'Housing', 'internet': 'Housing',
        'movie': 'Entertainment', 'game': 'Entertainment', 'cinema': 'Entertainment', 'bar': 'Entertainment',
        'clothes': 'Shopping', 'shoes': 'Shopping', 'shirt': 'Shopping', 'shopping': 'Shopping',
        'gym': 'Health', 'doctor': 'Health', 'pharmacy': 'Health', 'meds': 'Health',
    }

    for key, value in mapping.items():
        if key in text:
            return value

    return 'Other'


if __name__ == "__main__":
    # Test the parsing function
    test_text = "Spent 50 shekels on pizza"
    print(f"Testing parsing with: '{test_text}'")
    result = parse_expense(test_text)
    print("Parse Result:", result)

    # Test the insights function
    print("\nTesting insights generation...")
    test_totals = {"Food": 150.0, "Transport": 50.0, "Entertainment": 200.0}
    insight = generate_insights(test_totals, budget=500.0)
    print("Insight Result:", insight)
