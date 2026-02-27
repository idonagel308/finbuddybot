
import asyncio
import llm_helper
import logging

# Disable excessive logging for cleaner test output
logging.getLogger("httpx").setLevel(logging.WARNING)

async def test_intelligence_suite():
    print("🚀 Starting Intelligence & Accuracy Test Suite...\n")
    
    test_cases = [
        # --- English: Simple ---
        {"input": "Spent 50 on pizza", "expected_type": "expense", "expected_amt": 50, "expected_cat": "Food"},
        {"input": "Taxi was 45 dollars", "expected_type": "expense", "expected_amt": 139.94, "expected_cat": "Transport"}, # Based on current rate
        
        # --- English: Complex/Conversational ---
        {"input": "I just paid my rent, it was 3500", "expected_type": "expense", "expected_amt": 3500, "expected_cat": "Housing"},
        {"input": "Got my salary today! 12000 into the bank", "expected_type": "income", "expected_amt": 12000, "expected_cat": "Salary"},
        
        # --- Hebrew: Simple ---
        {"input": "50 שקל על אוכל", "expected_type": "expense", "expected_amt": 50, "expected_cat": "Food"},
        {"input": "קניתי נעליים ב-300", "expected_type": "expense", "expected_amt": 300, "expected_cat": "Shopping"},
        
        # --- Hebrew: Conversational ---
        {"input": "קיבלתי 500 שקלים בונוס", "expected_type": "income", "expected_amt": 500, "expected_cat": ["Gift", "Salary"]},
        {"input": "שילמתי ועד בית 150 שקל", "expected_type": "expense", "expected_amt": 150, "expected_cat": "Housing"},
        
        # --- Edge Cases / Negatives ---
        {"input": "Hello bot, how is the weather?", "expected_status": "not_transaction"},
        {"input": "Can you meet me at 5pm?", "expected_status": "not_transaction"},
        {"input": "123456", "expected_status": "not_transaction"}, # Bare number check
    ]
    
    passed = 0
    total = len(test_cases)
    
    for i, tc in enumerate(test_cases):
        print(f"[{i+1}/{total}] Testing: '{tc['input']}'")
        try:
            # parse_expense is synchronous in the current codebase
            result = llm_helper.parse_expense(tc['input'])
            
            if tc.get('expected_status') == 'not_transaction':
                if result.get('status') == 'not_transaction':
                    print("  ✅ PASS: Corrected identified as non-transaction")
                    passed += 1
                else:
                    print(f"  ❌ FAIL: Expected not_transaction but got {result}")
            else:
                if result.get('status') == 'success':
                    # Flexible check for amount (rounding) and category (list or string)
                    amt_match = abs(result.get('amount', 0) - tc['expected_amt']) < 0.1
                    
                    expected_cats = tc['expected_cat'] if isinstance(tc['expected_cat'], list) else [tc['expected_cat']]
                    cat_match = result.get('category') in expected_cats
                    
                    type_match = result.get('type') == tc['expected_type']
                    
                    if amt_match and cat_match and type_match:
                        print(f"  ✅ PASS: {result['type']} | {result['amount']} | {result['category']}")
                        passed += 1
                    else:
                        print(f"  ❌ FAIL: Expected {tc['expected_type']} {tc['expected_amt']} {tc['expected_cat']}, but got {result.get('type')} {result.get('amount')} {result.get('category')}")
                else:
                    print(f"  ❌ FAIL: Status was {result.get('status')}")
        except Exception as e:
            print(f"  💥 CRASH: {type(e).__name__}: {e}")
            
    print(f"\n--- Results: {passed}/{total} Passed ---")
    if passed == total:
        print("🎉 ALL INTELLIGENCE TESTS PASSED!")
    else:
        print("⚠️ Some tests failed. Check extraction logic.")

if __name__ == "__main__":
    asyncio.run(test_intelligence_suite())
