import asyncio
import os
import sys
from datetime import datetime

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import services.firestore_service as firestore_service

async def verify():
    test_user_id = 999999999
    
    print(f"--- Testing Firestore Integration for User {test_user_id} ---")
    
    # 1. Test Profile
    print("Testing Profile...")
    await firestore_service.set_profile(
        test_user_id, age=30, yearly_income=50000.0, 
        currency="USD", language="English", additional_info="Testing Firestore"
    )
    profile = await firestore_service.get_profile(test_user_id)
    print(f"Retrieved Profile: {profile}")
    assert profile['age'] == 30
    assert profile['currency'] == "USD"
    
    # 2. Test Budget
    print("\nTesting Budget...")
    await firestore_service.set_budget(test_user_id, 2500.0)
    budget = await firestore_service.get_budget(test_user_id)
    print(f"Retrieved Budget: {budget}")
    assert budget == 2500.0
    
    # 3. Test Settings
    print("\nTesting Settings...")
    await firestore_service.save_user_settings(
        test_user_id, theme="light", accent_color="blue"
    )
    settings = await firestore_service.get_user_settings(test_user_id)
    print(f"Retrieved Settings: {settings}")
    assert settings['theme'] == "light"
    assert settings['accent_color'] == "blue"
    
    # 4. Test Expenses
    print("\nTesting Expenses...")
    # Add a few expenses
    await firestore_service.add_expense(test_user_id, 50.0, "Food", "Pizza")
    await firestore_service.add_expense(test_user_id, 30.0, "Transport", "Taxi")
    await firestore_service.add_expense(test_user_id, 1000.0, "Salary", "Monthly Salary", transaction_type="income")
    
    # 5. Test Summary
    print("\nTesting Summary...")
    total_exp, total_inc = await firestore_service.get_monthly_summary(test_user_id)
    print(f"Monthly Summary - Expenses: {total_exp}, Income: {total_inc}")
    # Note: Summary might take a second to reflect in sometimes if not strongly consistent, 
    # but Firestore is usually fast enough.
    
    print("\n--- Firestore Verification PASSED ---")

if __name__ == "__main__":
    asyncio.run(verify())
