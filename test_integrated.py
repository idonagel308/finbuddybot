import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.llm_helper import parse_expense
from database.expense_operations import add_expense, delete_all_expenses
from database.user_management import set_profile
from database.analytics_engine import get_cash_flow_forecast
from datetime import datetime

async def test_llm_parsing():
    print("--- Testing LLM Parsing ---")
    
    # 1. Standard Expense
    res1 = parse_expense("spent 50 shekels on pizza")
    print(f"Standard Expense: {res1.get('status')} | Amount: {res1.get('amount')} | Category: {res1.get('category')} | Planned: {res1.get('planned')}")
    assert res1.get('status') == 'success'
    assert res1.get('type') == 'expense'
    
    # 2. Income
    res2 = parse_expense("received 5000 salary")
    print(f"Income: {res2.get('status')} | Amount: {res2.get('amount')} | Type: {res2.get('type')}")
    assert res2.get('status') == 'success'
    assert res2.get('type') == 'income'
    
    # 3. Planned Expense
    res3 = parse_expense("will pay 500 for rent next week")
    print(f"Planned: {res3.get('status')} | Amount: {res3.get('amount')} | Planned: {res3.get('planned')} | Due: {res3.get('due_date')}")
    assert res3.get('status') == 'success'
    assert res3.get('planned') is True
    assert res3.get('due_date') is not None
    
    print("OK - LLM Parsing Tests Passed\n")


async def test_analytics_and_db():
    print("--- Testing Database & Analytics (Business Mode) ---")
    test_user_id = 999999  # Dummy ID
    
    # Set to business profile
    await set_profile(test_user_id, age=30, yearly_income=100000, account_type="business")
    
    # Clear existing
    await delete_all_expenses(test_user_id)
    
    # Add historical expense
    await add_expense(test_user_id, amount=100, category="Shopping", description="supplies", transaction_type="expense")
    
    # Add planned expense for tomorrow
    tomorrow = datetime.now()
    due = f"{tomorrow.year}-{tomorrow.month:02d}-{(tomorrow.day % 28) + 1:02d}"
    await add_expense(test_user_id, amount=500, category="Housing", description="rent", transaction_type="expense", status="planned", due_date=due)
    
    # Add historical income
    await add_expense(test_user_id, amount=2000, category="Salary", description="paycheck", transaction_type="income")
    
    # Test forecast
    forecast = await get_cash_flow_forecast(test_user_id)
    print(f"Generated {len(forecast)} days of cash flow forecast.")
    
    # Find active days
    active_days = [d for d in forecast if d['historical_net'] != 0 or d['projected_net'] != 0]
    print(f"Found {len(active_days)} active days in forecast:")
    for d in active_days:
        print(f"  Date: {d['date']} | Historical Net: {d['historical_net']} | Projected Net: {d['projected_net']}")
        
    assert len(active_days) >= 2, "Expected at least one historical day and one projected day"
    
    # Clean up
    await delete_all_expenses(test_user_id)
    print("OK - Database & Analytics Tests Passed\n")

if __name__ == "__main__":
    asyncio.run(test_llm_parsing())
    asyncio.run(test_analytics_and_db())
    print("All Integration Tests Passed!")
