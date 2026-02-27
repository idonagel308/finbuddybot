"""
currency.py — Currency detection and conversion to NIS.

Fetches live exchange rates from a free API with hardcoded fallback rates.
Default base currency is NIS (Israeli New Shekel).
"""

import re
import logging
import urllib.request
import json
import time

logger = logging.getLogger(__name__)

# ── Fallback rates (approximate, updated Feb 2026) ──
# These are used when the API is unavailable.
# Rates are: 1 unit of foreign currency = X NIS
FALLBACK_RATES = {
    'USD': 3.65,
    'EUR': 3.95,
    'GBP': 4.60,
    'CAD': 2.65,
    'AUD': 2.35,
    'JPY': 0.024,
    'CHF': 4.10,
    'RUB': 0.04,
    'TRY': 0.11,
    'NIS': 1.0,
    'ILS': 1.0,
}

# ── Live rate cache ──
_rate_cache: dict = {}
_cache_timestamp: float = 0
CACHE_TTL = 21600  # Refresh rates every 6 hours (rates don't move meaningfully within a day)

API_URL = "https://api.frankfurter.app/latest?from=ILS"


def _fetch_live_rates() -> dict:
    """Fetches live exchange rates from Frankfurter API (free, no key needed)."""
    global _rate_cache, _cache_timestamp

    # Return cached rates if still fresh
    if _rate_cache and (time.time() - _cache_timestamp) < CACHE_TTL:
        return _rate_cache

    try:
        req = urllib.request.Request(API_URL, headers={'User-Agent': 'FinTechBot/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            data = json.loads(resp.read().decode())

        # API returns rates FROM ILS, e.g. {"ILS": 1, "USD": 0.27}
        # We need the inverse: 1 USD = X ILS
        raw_rates = data.get("rates", {})
        converted = {}
        for currency, rate in raw_rates.items():
            if rate > 0:
                converted[currency] = round(1.0 / rate, 4)

        converted['NIS'] = 1.0
        converted['ILS'] = 1.0

        _rate_cache = converted
        _cache_timestamp = time.time()
        logger.info(f"Fetched live exchange rates: {len(converted)} currencies")
        return converted

    except Exception as e:
        logger.warning(f"Failed to fetch live rates: {type(e).__name__}. Using fallback.")
        return FALLBACK_RATES


def get_rate(currency_code: str) -> float:
    """Returns NIS equivalent of 1 unit of the given currency."""
    rates = _fetch_live_rates()
    return rates.get(currency_code.upper(), FALLBACK_RATES.get(currency_code.upper(), 1.0))


def convert_to_nis(amount: float, currency_code: str) -> float:
    """Converts an amount from a foreign currency to NIS."""
    if currency_code.upper() in ('NIS', 'ILS'):
        return amount
    rate = get_rate(currency_code)
    return round(amount * rate, 2)


# ── Currency Detection from Text ──

# Maps phrases/symbols to currency codes
CURRENCY_PATTERNS = {
    # USD
    r'\$': 'USD',
    r'\bdollars?\b': 'USD',
    r'\busd\b': 'USD',
    r'\bדולר(ים)?\b': 'USD',

    # EUR
    r'€': 'EUR',
    r'\beuros?\b': 'EUR',
    r'\beur\b': 'EUR',
    r'\bאירו\b': 'EUR',

    # GBP
    r'£': 'GBP',
    r'\bpounds?\b': 'GBP',
    r'\bgbp\b': 'GBP',
    r'\bלירות?\b': 'GBP',

    # NIS / ILS (default)
    r'\bnis\b': 'NIS',
    r'\bils\b': 'NIS',
    r'\bshekel(s|im)?\b': 'NIS',
    r'\bש"?ח\b': 'NIS',
    r'\bשקל(ים)?\b': 'NIS',

    # Others
    r'\bcad\b': 'CAD',
    r'\baud\b': 'CAD',
    r'¥': 'JPY',
    r'\byen\b': 'JPY',
}

# Pre-compiled patterns for O(1)-setup matching
_COMPILED_CURRENCY_PATTERNS = [(re.compile(p), code) for p, code in CURRENCY_PATTERNS.items()]


def detect_currency(text: str) -> str:
    """
    Detects currency from user text. Returns the currency code.
    Defaults to 'NIS' if no currency is detected.
    """
    text_lower = text.lower()
    for regex, code in _COMPILED_CURRENCY_PATTERNS:
        if regex.search(text_lower):
            return code
    return 'NIS'


def format_conversion(original_amount: float, currency: str, nis_amount: float) -> str:
    """Formats a conversion message for display."""
    symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥'}
    symbol = symbols.get(currency, currency)
    rate = get_rate(currency)
    return f"💱 {symbol}{original_amount:.2f} → ₪{nis_amount:.2f} (rate: {rate:.2f})"


if __name__ == "__main__":
    # Test currency detection
    tests = [
        ("spent 50 dollars on food", "USD"),
        ("שילמתי 200 שקל בסופר", "NIS"),
        ("paid €30 for Netflix", "EUR"),
        ("taxi 35", "NIS"),
        ("bought shoes for 100 euros", "EUR"),
        ("50 דולר על פיצה", "USD"),
        ("£20 on coffee", "GBP"),
    ]

    print("=== Currency Detection Tests ===")
    for text, expected in tests:
        detected = detect_currency(text)
        status = "✅" if detected == expected else "❌"
        print(f"  {status} \"{text}\" → {detected} (expected {expected})")

    print("\n=== Conversion Tests ===")
    for curr in ['USD', 'EUR', 'GBP']:
        amount = 100
        nis = convert_to_nis(amount, curr)
        print(f"  {amount} {curr} = ₪{nis:.2f}")
        print(f"  {format_conversion(amount, curr, nis)}")
