"""
Targeted NLP test against services/llm_helper.py (the REAL one)
Run: python test_nlp_services.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from services import llm_helper

TEST_CASES = [
    ("Spent 50 on pizza",           "success",          "Food",       50),
    ("אכלתי המבורגר ב20",            "success",          "Food",       20),
    ("אכלתי המבורגר ב30 שקל",        "success",          "Food",       30),
    ("קניתי שווארמה ב-45 שקל",       "success",          "Food",       45),
    ("taxi 35",                      "success",          "Transport",  35),
    ("50 bus",                       "success",          "Transport",  50),
    ("I earned 5000 from work",      "success",          None,         5000),
    ("Income of 1200 shekels",       "success",          None,         1200),
    ("הוצאתי 100 שקל על בגדים",       "success",          "Shopping",   100),
    ("שלום",                         "not_transaction",  None,         None),
    ("What is my balance?",          "not_transaction",  None,         None),
]

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

passes = 0
fails = 0

print(f"\n{'─'*75}")
print(f"{'INPUT':<35} {'GOT':<18} {'EXPECTED':<18} {'OK?'}")
print(f"{'─'*75}")

for text, exp_status, exp_cat, exp_amount in TEST_CASES:
    result = llm_helper.parse_expense(text)
    got_status = result.get("status", "?")
    got_cat = result.get("category", "-")
    got_amount = result.get("amount", "-")

    status_ok = (got_status == exp_status)
    cat_ok = (exp_cat is None) or (got_cat == exp_cat)
    amount_ok = (exp_amount is None) or (abs(float(got_amount or 0) - exp_amount) < 0.01)
    
    ok = status_ok and cat_ok and amount_ok
    icon = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    
    if ok:
        passes += 1
    else:
        fails += 1

    got_display = f"{got_status}/{got_cat}/{got_amount}"
    exp_display = f"{exp_status}/{exp_cat or '*'}/{exp_amount or '*'}"
    print(f"{text:<35} {got_display:<18} {exp_display:<18} {icon}")

print(f"{'─'*75}")
total = passes + fails
print(f"{BOLD}Results: {GREEN}{passes}{RESET}{BOLD}/{total} passed, {RED}{fails}{RESET}{BOLD}/{total} failed{RESET}\n")
sys.exit(0 if fails == 0 else 1)
