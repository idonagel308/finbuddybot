
import os
import sqlite3
import threading
import time
from dotenv import load_dotenv
import services.database as db
import services.sheets_etl as sheets_etl

load_dotenv()

def sync_all_to_cloud():
    print("🚀 Starting Full SQLite -> Google Sheets Sync...")
    
    # 1. Get all expenses from SQLite
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, date, amount, category, description FROM expenses")
            rows = cursor.fetchall()
            
        if not rows:
            print("ℹ️ No data found in local SQLite. Nothing to sync.")
            return

        print(f"📦 Found {len(rows)} transactions locally.")
        
        # 2. Get unique user IDs to sync by user (to use the batch rewrite logic)
        user_ids = list(set(r[1] for r in rows))
        print(f"👥 Syncing data for {len(user_ids)} users...")
        
        for uid in user_ids:
            user_rows = [r for r in rows if r[1] == uid]
            print(f"   - Syncing {len(user_rows)} rows for User {uid}...")
            
            # Format for gspread
            formatted = []
            for r in user_rows:
                formatted.append([r[0], r[1], r[2], r[3], r[4], r[5] or ""])
            
            # We use the existing rewrite logic to ensure it's clean
            sheets_etl.rewrite_user_expenses(uid, formatted)
            
        print("✅ Sync Complete! Your cloud storage is now identical to your local cache.")
        
    except Exception as e:
        print(f"❌ Sync failed: {e}")

if __name__ == "__main__":
    sync_all_to_cloud()
