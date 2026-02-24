import os
import re
import json
import time
import math
import logging
import google.generativeai as genai
from dotenv import load_dotenv
import currency as curr

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
_insight_model_cache = {}

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


# ── Intent Classification ──

# Signal words that suggest an expense message
_EXPENSE_SIGNALS_EN = {
    'spent', 'paid', 'bought', 'cost', 'price', 'charged', 'pay',
    'on', 'for', 'at', 'tip', 'bill', 'fee', 'ordered',
}
_EXPENSE_SIGNALS_HE = {
    'שילמתי', 'קניתי', 'הוצאתי', 'עלה', 'עלתה', 'עולה', 'שקל',
    'שקלים', 'ב-', 'על', 'קנה', 'שילם', 'הוצאה', 'תשלום',
}

# Words that clearly indicate NOT an expense
_NON_EXPENSE_SIGNALS = {
    'hello', 'hi', 'hey', 'how', 'what', 'who', 'when', 'where', 'why',
    'thanks', 'thank', 'please', 'help', 'sorry', 'yes', 'no', 'ok',
    'שלום', 'היי', 'מה', 'איך', 'למה', 'מי', 'תודה', 'בבקשה', 'כן', 'לא',
}


def _classify_intent(text: str) -> str:
    """
    Fast pre-filter to classify message intent.
    Returns: 'expense', 'not_expense', or 'ambiguous'
    """
    if not text:
        return 'not_expense'

    text_lower = text.lower().strip()
    words = set(re.split(r'\s+', text_lower))
    has_number = bool(re.search(r'\d', text))

    # Pure greeting / question with no number → clearly not an expense
    if not has_number:
        if words & _NON_EXPENSE_SIGNALS or text_lower.endswith('?'):
            return 'not_expense'
        # No number at all → very unlikely to be an expense
        return 'not_expense'

    # Has a number — check for expense signal words
    if words & _EXPENSE_SIGNALS_EN or words & _EXPENSE_SIGNALS_HE:
        return 'expense'

    # Has a number + a known category keyword → likely expense
    # (e.g., "pizza 50" or "50 taxi")
    for word in words:
        if _map_category(word) != 'Other':
            return 'expense'

    # Has a number but no clear signal — ambiguous, let LLM decide
    return 'ambiguous'


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
    if not isinstance(amount, (int, float)) or math.isnan(amount) or math.isinf(amount) or amount <= 0 or amount > MAX_AMOUNT:
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


def _apply_currency_conversion(parsed: dict, original_text: str) -> dict:
    """
    Detects currency from the original user text and converts to NIS if needed.
    Adds 'original_amount', 'original_currency', and 'converted' keys.
    """
    if not parsed:
        return parsed

    detected = curr.detect_currency(original_text)
    original_amount = parsed['amount']

    if detected != 'NIS':
        nis_amount = curr.convert_to_nis(original_amount, detected)
        parsed['original_amount'] = original_amount
        parsed['original_currency'] = detected
        parsed['amount'] = nis_amount
        parsed['converted'] = True
    else:
        parsed['original_currency'] = 'NIS'
        parsed['converted'] = False

    return parsed


def _fuzzy_match_category(raw_category: str) -> str:
    """Attempts to match a raw category string to an allowed category."""
    if not raw_category:
        return 'Other'
    raw_lower = raw_category.lower()
    for allowed in ALLOWED_CATEGORIES:
        if allowed.lower() in raw_lower or raw_lower in allowed.lower():
            return allowed
    return 'Other'


def generate_insights(
    totals: dict, 
    age: int = None, 
    yearly_income: float = None, 
    budget: float = None, 
    recent_expenses: list = None,
    currency: str = 'NIS',
    additional_info: str = None
):
    """
    Generates tailored financial advice based on structured spending data.
    """
    if not api_key:
        return "⚠️ API Key missing. Cannot generate insights."

    # Format context for segments
    profile_context = ""
    if age: profile_context += f"User Age: {age}\n"
    if yearly_income: profile_context += f"Yearly Estimated Income: {currency} {yearly_income}\n"
    if budget: profile_context += f"Monthly Budget: {currency} {budget}\n"
    if additional_info: profile_context += f"User Goals/Info: {additional_info}\n"

    # Prepare recent expenses for JSON output
    repr_recent = []
    if recent_expenses:
        for e in recent_expenses[:5]:
            # Assuming e is (id, timestamp, amount, category, description)
            # Adjust this if the structure of recent_expenses is different
            repr_recent.append({
                "date": e[1][5:10], # Assuming timestamp is a string like "YYYY-MM-DD HH:MM:SS"
                "amount": e[2],
                "category": e[3],
                "description": e[4]
            })

    prompt = f"""
    You are an elite personal financial coach. Analyze this user's data and provide 3 HIGHLY SPECIFIC, actionable tips.
    
    DATA POINTS:
    {profile_context}
    Breakdown by Category:
    {json.dumps(totals, indent=2)}
    
    Recent Expenses:
    {json.dumps(repr_recent, indent=2) if repr_recent else 'None'}
    
    GUIDELINES:
    1. Be concise (max 60 words total).
    2. Identify the biggest spending category or an unusual trend.
    3. If over budget, give a specific saving strategy.
    4. If under budget, encourage them.
    5. Plain text only, NO markdown, NO emojis (I will add them).
    """

    for model_name in MODELS_TO_TRY:
        try:
            if model_name not in _insight_model_cache:
                _insight_model_cache[model_name] = genai.GenerativeModel(
                    model_name,
                    generation_config=genai.GenerationConfig(temperature=0.5),
                )
            response = _insight_model_cache[model_name].generate_content(prompt)
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
        return {"status": "not_expense"}

    # --- Pre-filter: classify intent ---
    intent = _classify_intent(safe_text)
    if intent == 'not_expense':
        return {"status": "not_expense"}

    # --- Try LLM First ---
    if api_key:
        prompt = f"""Extract expense info from the user message. User may write in English or Hebrew.
Return JSON with: "amount" (number), "category" (one of: Housing, Food, Transport, Entertainment, Shopping, Health, Education, Financial, Other), "description" (short string).
Return null if not an expense.
Category hints: Housing=rent/bills/חשמל/שכירות, Food=groceries/restaurant/סופר/קפה, Transport=taxi/bus/דלק/מונית, Entertainment=movies/Netflix/בילוי, Shopping=clothes/electronics/קניות, Health=doctor/gym/רופא, Education=books/courses/לימודים, Financial=insurance/tax/ביטוח.
Ignore currency words (שקל, dollars, etc), just extract the number.

Examples:
"spent 50 on pizza" → {{"amount":50,"category":"Food","description":"pizza"}}
"שילמתי 200 בסופר" → {{"amount":200,"category":"Food","description":"supermarket"}}
"hello" → null

Extract from: "{safe_text}"
"""

        for model_name in MODELS_TO_TRY:
            try:
                if model_name not in _model_cache:
                    _model_cache[model_name] = genai.GenerativeModel(
                        model_name,
                        generation_config=genai.GenerationConfig(
                            response_mime_type="application/json",
                            temperature=0.1,
                        ),
                    )
                response = _model_cache[model_name].generate_content(prompt)

                content = response.text.strip()

                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    # Fallback: try to extract JSON object from response
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(0))
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode JSON from {model_name}: {content[:100]}")
                            continue
                    else:
                        logger.warning(f"No JSON in response from {model_name}: {content[:100]}")
                        continue

                # LLM returned null → it decided this is not an expense
                if data is None:
                    return {"status": "not_expense"}

                validated = _validate_parsed_expense(data)
                if validated:
                    result = _apply_currency_conversion(validated, text)
                    result["status"] = "success"
                    return result
                else:
                    logger.warning(f"LLM returned invalid expense data: trying next model")
                    continue

            except Exception as e:
                error_str = str(e)
                logger.warning(f"parse_expense: {model_name}: {type(e).__name__}")
                if "429" in error_str or "exhausted" in error_str.lower():
                    time.sleep(1)
                continue

    logger.info("LLM unavailable. Falling back to Regex.")

    # --- Regex Fallback (only if intent was 'expense' or 'ambiguous') ---
    if intent == 'not_expense':
        return {"status": "not_expense"}

    text_lower = safe_text.lower()

    # Pattern 1: Number + text (e.g. "50 pizza", "30 שקל")
    match = re.search(r'(\d+(?:\.\d+)?)\s*([a-zA-Z\u0590-\u05FF\s]+)', text_lower)
    if match:
        amount = float(match.group(1))
        if 0 < amount <= MAX_AMOUNT:
            raw_text = match.group(2).strip()
            clean_category = re.sub(
                r'^(on|for|spent|at|the|a|ב-?|על|של|שקל|שקלים|ש"ח|nis|shekels|dollars|שילמתי|קניתי|הוצאתי)\s*',
                '', raw_text, flags=re.IGNORECASE
            ).strip()
            if clean_category and _map_category(clean_category) != 'Other':
                result = _apply_currency_conversion({
                    "amount": amount,
                    "category": _map_category(clean_category),
                    "description": clean_category
                }, text)
                result["status"] = "success"
                return result
            elif clean_category:
                # Has number + text but we can't map category
                return {"status": "no_category", "amount": amount, "text": clean_category}

    # Pattern 2: Text + number (e.g. "pizza 50")
    match2 = re.search(r'([a-zA-Z\u0590-\u05FF\s]+)\s*(\d+(?:\.\d+)?)', text_lower)
    if match2:
        raw_text = match2.group(1).strip()
        amount = float(match2.group(2))
        if 0 < amount <= MAX_AMOUNT:
            mapped = _map_category(raw_text)
            if mapped != 'Other':
                result = _apply_currency_conversion({
                    "amount": amount,
                    "category": mapped,
                    "description": raw_text
                }, text)
                result["status"] = "success"
                return result
            else:
                return {"status": "no_category", "amount": amount, "text": raw_text}

    # Has a number but we couldn't extract anything meaningful
    if re.search(r'\d', safe_text):
        return {"status": "no_category"}

    return {"status": "not_expense"}


# Pre-built category mapping — O(1) lookup instead of O(n) scan
_CATEGORY_MAP = {
    # Food — English
    'food': 'Food', 'pizza': 'Food', 'burger': 'Food', 'sushi': 'Food',
    'restaurant': 'Food', 'coffee': 'Food', 'groceries': 'Food', 'snack': 'Food',
    'lunch': 'Food', 'dinner': 'Food', 'breakfast': 'Food', 'meal': 'Food',
    'supermarket': 'Food', 'cafe': 'Food', 'bakery': 'Food', 'delivery': 'Food',
    'falafel': 'Food', 'shawarma': 'Food', 'hummus': 'Food',
    # Food — Hebrew
    'אוכל': 'Food', 'פיצה': 'Food', 'סופר': 'Food', 'מסעדה': 'Food',
    'קפה': 'Food', 'ארוחה': 'Food', 'משלוח': 'Food', 'מאפייה': 'Food',
    'פלאפל': 'Food', 'שווארמה': 'Food', 'חומוס': 'Food', 'מכולת': 'Food',
    # Transport — English
    'taxi': 'Transport', 'bus': 'Transport', 'train': 'Transport',
    'fuel': 'Transport', 'gas': 'Transport', 'flight': 'Transport',
    'uber': 'Transport', 'gett': 'Transport', 'parking': 'Transport',
    'metro': 'Transport', 'car': 'Transport', 'toll': 'Transport',
    # Transport — Hebrew
    'מונית': 'Transport', 'אוטובוס': 'Transport', 'רכבת': 'Transport',
    'דלק': 'Transport', 'חנייה': 'Transport', 'תחבורה': 'Transport',
    'רכב': 'Transport', 'טיסה': 'Transport',
    # Housing — English
    'rent': 'Housing', 'electricity': 'Housing', 'water': 'Housing',
    'bill': 'Housing', 'internet': 'Housing', 'utilities': 'Housing',
    'maintenance': 'Housing', 'plumber': 'Housing',
    # Housing — Hebrew
    'שכירות': 'Housing', 'חשמל': 'Housing', 'מים': 'Housing',
    'ארנונה': 'Housing', 'אינטרנט': 'Housing', 'ועד בית': 'Housing',
    'שיפוץ': 'Housing', 'אינסטלטור': 'Housing',
    # Entertainment — English
    'movie': 'Entertainment', 'game': 'Entertainment', 'cinema': 'Entertainment',
    'bar': 'Entertainment', 'netflix': 'Entertainment', 'spotify': 'Entertainment',
    'concert': 'Entertainment', 'show': 'Entertainment', 'party': 'Entertainment',
    'vacation': 'Entertainment', 'hotel': 'Entertainment', 'trip': 'Entertainment',
    # Entertainment — Hebrew
    'סרט': 'Entertainment', 'קולנוע': 'Entertainment', 'הופעה': 'Entertainment',
    'בילוי': 'Entertainment', 'חופשה': 'Entertainment', 'מלון': 'Entertainment',
    'משחק': 'Entertainment', 'פאב': 'Entertainment',
    # Shopping — English
    'clothes': 'Shopping', 'shoes': 'Shopping', 'shirt': 'Shopping',
    'shopping': 'Shopping', 'amazon': 'Shopping', 'electronics': 'Shopping',
    'phone': 'Shopping', 'laptop': 'Shopping', 'furniture': 'Shopping',
    'gift': 'Shopping', 'online': 'Shopping',
    # Shopping — Hebrew
    'בגדים': 'Shopping', 'נעליים': 'Shopping', 'קניות': 'Shopping',
    'אלקטרוניקה': 'Shopping', 'טלפון': 'Shopping', 'ריהוט': 'Shopping',
    'מתנה': 'Shopping',
    # Health — English
    'gym': 'Health', 'doctor': 'Health', 'pharmacy': 'Health', 'meds': 'Health',
    'dentist': 'Health', 'therapy': 'Health', 'hospital': 'Health',
    'vitamins': 'Health', 'clinic': 'Health',
    # Health — Hebrew
    'רופא': 'Health', 'מרקחת': 'Health', 'בריאות': 'Health',
    'חדר כושר': 'Health', 'שיניים': 'Health', 'תרופות': 'Health',
    'קופת חולים': 'Health', 'בית חולים': 'Health',
    # Education — English
    'book': 'Education', 'course': 'Education', 'tuition': 'Education',
    'school': 'Education', 'university': 'Education', 'class': 'Education',
    'udemy': 'Education', 'tutorial': 'Education',
    # Education — Hebrew
    'ספר': 'Education', 'קורס': 'Education', 'לימודים': 'Education',
    'אוניברסיטה': 'Education', 'שיעור': 'Education', 'מכללה': 'Education',
    # Financial
    'insurance': 'Financial', 'tax': 'Financial', 'bank': 'Financial',
    'savings': 'Financial', 'investment': 'Financial', 'fee': 'Financial',
    'loan': 'Financial', 'mortgage': 'Financial', 'debt': 'Financial',
    # Financial — Hebrew
    'ביטוח': 'Financial', 'מס': 'Financial', 'בנק': 'Financial',
    'חיסכון': 'Financial', 'השקעה': 'Financial', 'עמלה': 'Financial',
    'הלוואה': 'Financial', 'משכנתא': 'Financial',
}

# Multi-word keys need substring matching — extract them for the fallback path
_MULTIWORD_KEYS = {k: v for k, v in _CATEGORY_MAP.items() if ' ' in k}


def _map_category(text):
    """Maps a raw text keyword to a clean category string. O(1) for single-word matches."""
    text_lower = text.lower()

    # Fast path: direct lookup
    result = _CATEGORY_MAP.get(text_lower)
    if result:
        return result

    # Check individual words
    for word in text_lower.split():
        result = _CATEGORY_MAP.get(word)
        if result:
            return result

    # Slow path: multi-word substring check (e.g. 'חדר כושר', 'ועד בית')
    for key, value in _MULTIWORD_KEYS.items():
        if key in text_lower:
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
