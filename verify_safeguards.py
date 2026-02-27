
import os
import sqlite3
import database as db
import logging

# Setup a clean test environment
TEST_DB = "test_safeguard.db"
TEST_BAK = TEST_DB + ".bak"
db.DB_NAME = TEST_DB

# Ensure files are gone
if os.path.exists(TEST_DB): os.remove(TEST_DB)
if os.path.exists(TEST_BAK): os.remove(TEST_BAK)

def test_backup():
    print("Testing backup_db...")
    db.init_db()  # Should create backup if exists, but first time just creates DB
    if not os.path.exists(TEST_DB):
        print("FAIL: DB not created")
        return
    
    # Add some data
    db.add_expense(999, 100.0, "Food", "Initial")
    db.close_connection()
    
    # Trigger backup
    db.backup_db()
    if os.path.exists(TEST_BAK):
        print("PASS: Backup created")
    else:
        print("FAIL: Backup NOT created")

def test_sync_protection():
    print("\nTesting sync protection...")
    # Add 20 records locally
    for i in range(20):
        db.add_expense(999, 10.0, "Food", f"Ex {i}")
    
    # 1. Test Empty Cloud Protection
    print("Simulating empty cloud recovery...")
    class MockETL:
        def fetch_all_data(self): return []
    
    db.sheets_etl = MockETL()
    db.close_connection()
    db.sync_from_sheets()
    
    # Check if local data is still there
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        if count >= 21:
            print(f"PASS: Local data preserved ({count} records)")
        else:
            print(f"FAIL: Local data wiped! ({count} records)")

    # 2. Test Small Cloud Protection (Integrity Check)
    print("Simulating suspiciously small cloud recovery (5 rows vs 21 local)...")
    class MockETLSmall:
        def fetch_all_data(self): return [{'id':1, 'user_id':999, 'date':'now', 'amount':10.0, 'category':'Food', 'description':''}] * 5
    
    db.sheets_etl = MockETLSmall()
    db.close_connection()
    db.sync_from_sheets()
    
    with db.get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        if count >= 21:
            print(f"PASS: Significant data loss prevented ({count} records)")
        else:
            print(f"FAIL: Suspiciously small cloud data overwrote local truth! ({count} records)")

if __name__ == "__main__":
    try:
        test_backup()
        test_sync_protection()
    finally:
        # Cleanup
        if os.path.exists(TEST_DB): os.remove(TEST_DB)
        if os.path.exists(TEST_BAK): os.remove(TEST_BAK)
