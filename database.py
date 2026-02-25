import sqlite3
import math
import logging
import threading
import os
from datetime import datetime
from contextlib import contextmanager

import sheets_etl

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "fintech.db"

# Validation constants
MAX_AMOUNT = 1_000_000  # Maximum single expense amount
MAX_DESCRIPTION_LENGTH = 200
ALLOWED_CATEGORIES = {
    'Housing', 'Food', 'Transport', 'Entertainment',
    'Shopping', 'Health', 'Education', 'Financial', 'Other'
}


@contextmanager
def get_connection():
    """Context manager for safe database connections. Uses SQLite (Hot Cache)."""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(DB_NAME, timeout=10)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    yield _local.conn


def close_connection():
    """Closes the thread-local database connection if it exists. Used for testing/cleanup."""
    if hasattr(_local, 'conn') and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


_local = threading.local()


def init_db():
    """Initializes the SQLite database. Dialect-agnostic hooks removed (reverting to pure SQLite)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # 1. Expenses Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id BIGINT NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount > 0),
                    category TEXT NOT NULL,
                    description TEXT
                )
            ''')

            # 2. Indexes
            cursor.execute('''CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date)''')
            cursor.execute('''CREATE INDEX IF NOT EXISTS idx_expenses_user_category ON expenses(user_id, category)''')

            # 3. Budgets Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budgets (
                    user_id BIGINT PRIMARY KEY,
                    amount REAL NOT NULL CHECK(amount > 0)
                )
            ''')

            # 4. Profiles Table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id BIGINT PRIMARY KEY,
                    age INTEGER,
                    yearly_income REAL,
                    currency TEXT DEFAULT 'NIS',
                    additional_info TEXT
                )
            ''')

            # Local Migration helpers
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN yearly_income REAL")
            except: pass
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN currency TEXT DEFAULT 'NIS'")
            except: pass
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN additional_info TEXT")
            except: pass

            conn.commit()
            logger.info("Database initialized (SQLite Cache).")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")


def _validate_expense(amount: float, category: str, description: str = ""):
    """Validates expense data before insertion."""
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError(f"Amount must be a positive number, got: {type(amount)}")
    if amount > MAX_AMOUNT:
        raise ValueError(f"Amount exceeds maximum allowed ({MAX_AMOUNT})")
    # Guard against NaN/infinity
    if math.isnan(amount) or math.isinf(amount):
        raise ValueError("Amount cannot be NaN or infinity")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters")


def _validate_user_id(user_id):
    """Ensures user_id is a valid integer."""
    if not isinstance(user_id, int) or user_id < 0:
        raise ValueError(f"Invalid user_id: {user_id}")


def add_expense(user_id: int, amount: float, category: str, description: str = ""):
    """Adds a new expense to SQLite and mirrors to Google Sheets."""
    _validate_user_id(user_id)
    _validate_expense(amount, category, description)
    if description:
        description = description[:MAX_DESCRIPTION_LENGTH].strip()

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            date_str = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO expenses (user_id, date, amount, category, description)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, date_str, amount, category, description))
            
            inserted_id = cursor.lastrowid
            conn.commit()
            
            # Mirror to Sheets
            sheets_etl.append_expense(inserted_id, user_id, date_str, amount, category, description)
            
            logger.info(f"Added expense {inserted_id} for user {user_id}")
            return inserted_id
    except Exception as e:
        logger.error(f"Error adding expense: {e}")
        raise

def get_recent_expenses(user_id: int = None, limit: int = 5):
    """Retrieves most recent expenses from SQLite cache."""
    limit = min(max(1, limit), 50)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT id, date, amount, category, description FROM expenses"
            params = []
            if user_id is not None:
                query += " WHERE user_id = ?"
                params.append(user_id)
            query += " ORDER BY date DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, tuple(params))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching expenses: {e}")
        return []


def _month_range(year: int = None, month: int = None):
    """
    Returns (start_date, end_date) strings for a given month.
    Uses the current month if year/month are not provided.
    start_date is inclusive, end_date is exclusive (first day of next month).
    """
    now = datetime.now()
    y = year or now.year
    m = month or now.month

    start = datetime(y, m, 1).isoformat()
    # Roll to first day of next month
    if m == 12:
        end = datetime(y + 1, 1, 1).isoformat()
    else:
        end = datetime(y, m + 1, 1).isoformat()
    return start, end


def get_monthly_summary(user_id: int, year: int = None, month: int = None):
    """Calculates total expenses for a month from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            start, end = _month_range(year, month)
            cursor.execute('''
                SELECT SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND date >= ? AND date < ?
            ''', (user_id, start, end))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0.0
    except Exception as e:
        logger.error(f"Error fetching summary: {e}")
        return 0.0


def get_yearly_month_totals(user_id: int, year: int = None) -> dict:
    """Returns monthly totals for a year from cache."""
    _validate_user_id(user_id)
    if year is None: year = datetime.now().year
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT CAST(strftime('%m', date) AS INTEGER) as month, SUM(amount) as total
                FROM expenses
                WHERE user_id = ? AND strftime('%Y', date) = ?
                GROUP BY month
                ORDER BY month
            ''', (user_id, str(year)))
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.error(f"Error getting yearly totals: {e}")
        return {}


def get_monthly_expenses(user_id: int, year: int = None, month: int = None):
    """Retrieves monthly expenses from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            start, end = _month_range(year, month)
            cursor.execute('''
                SELECT id, date, amount, category, description 
                FROM expenses 
                WHERE user_id = ? AND date >= ? AND date < ?
                ORDER BY date DESC
            ''', (user_id, start, end))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching monthly expenses: {e}")
        return []


def get_category_totals(user_id: int, year: int = None, month: int = None):
    """Returns category totals from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            start, end = _month_range(year, month)
            cursor.execute('''
                SELECT category, SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND date >= ? AND date < ?
                GROUP BY category
            ''', (user_id, start, end))
            return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception as e:
        logger.error(f"Error fetching category totals: {e}")
        return {}


def delete_expense(user_id: int, expense_id: int) -> bool:
    """Deletes an expense from SQLite and mirrors to Sheets."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM expenses WHERE id = ? AND user_id = ?',
                (expense_id, user_id)
            )
            conn.commit()
            success = cursor.rowcount > 0
            
            if success:
                # Mirror to Sheets
                sheets_etl.delete_expense(expense_id)
                
            return success
    except Exception as e:
        logger.error(f"Error deleting expense: {e}")
        return False


def get_last_expense_id(user_id: int) -> int | None:
    """Returns last ID from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM expenses WHERE user_id = ? ORDER BY date DESC LIMIT 1',
                (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error fetching last expense: {e}")
        return None


def export_expenses_csv(user_id: int) -> str:
    """Exports CSV from cache."""
    import csv, io
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT date, amount, category, description FROM expenses WHERE user_id = ? ORDER BY date DESC',
                (user_id,)
            )
            rows = cursor.fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Amount', 'Category', 'Description'])
        for row in rows:
            writer.writerow([row[0][:10], row[1], row[2], row[3] or ''])
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        return ""


def set_budget(user_id: int, amount: float):
    """Sets/updates budget in cache."""
    if amount <= 0 or amount > MAX_AMOUNT:
        raise ValueError(f"Budget must be between 0 and {MAX_AMOUNT}")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO budgets (user_id, amount) VALUES (?, ?)', (user_id, amount))
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting budget: {e}")
        raise


def get_budget(user_id: int) -> float | None:
    """Returns budget from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT amount FROM budgets WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error fetching budget: {e}")
        return None


def set_profile(user_id: int, age: int, yearly_income: float, currency: str = 'NIS', additional_info: str = ""):
    """Sets/updates profile in cache."""
    _validate_user_id(user_id)
    if not isinstance(age, int) or not (13 <= age <= 120):
        raise ValueError(f"Age must be between 13 and 120, got: {age}")
    if not isinstance(yearly_income, (int, float)) or yearly_income < 0:
        raise ValueError(f"Yearly income must be positive")
    if additional_info and len(additional_info) > 1000:
        raise ValueError(f"Additional info exceeds 1000 characters")
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO profiles (user_id, age, yearly_income, currency, additional_info) 
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, age, yearly_income, currency, additional_info))
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting profile: {e}")
        raise


def get_profile(user_id: int) -> dict | None:
    """Returns profile from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT age, yearly_income, currency, additional_info FROM profiles WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'age': row[0], 'yearly_income': row[1] or 0.0,
                    'currency': row[2] or 'NIS', 'additional_info': row[3] or ""
                }
            return None
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        return None


def delete_all_expenses(user_id: int) -> int:
    """Deletes ALL expenses (local only, user must wipe Sheets manually or we can batch delete)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM expenses WHERE user_id = ?', (user_id,))
            conn.commit()
            count = cursor.rowcount
            
        if count > 0:
            _sync_local_to_sheets_for_user(user_id)
            
        return count
    except Exception as e:
        logger.error(f"Error deleting all expenses: {e}")
        return 0


def delete_monthly_expenses(user_id: int) -> int:
    """Deletes current month locally."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            start, end = _month_range()
            cursor.execute('DELETE FROM expenses WHERE user_id = ? AND date >= ? AND date < ?', (user_id, start, end))
            conn.commit()
            count = cursor.rowcount
            
        if count > 0:
            _sync_local_to_sheets_for_user(user_id)
            
        return count
    except Exception as e:
        logger.error(f"Error deleting monthly expenses: {e}")
        return 0

def _sync_local_to_sheets_for_user(user_id: int):
    """Pushes the current state of SQLite for a specific user to Google Sheets for mass updates."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, user_id, date, amount, category, description FROM expenses WHERE user_id = ? ORDER BY date ASC',
                (user_id,)
            )
            rows = cursor.fetchall()
            
        # Format for gspread
        formatted = []
        for r in rows:
            formatted.append([r[0], r[1], r[2], r[3], r[4], r[5] or ""])
            
        # Background thread so the Telegram UI doesn't hang
        threading.Thread(target=sheets_etl.rewrite_user_expenses, args=(user_id, formatted)).start()
        logger.info(f"Triggered background wholesale sync for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to initiate wholesale sync: {e}")


def sync_from_sheets():
    """
    Recovers the local SQLite cache from Google Sheets.
    Senior Developer Note: This is an idempotent 'Cold Start' recovery logic.
    It logs specific failures but allows the application to remain functional (even if data is stale).
    """
    logger.info("⚡ [STARTUP] Initiating Secure Sync from Google Sheets Source of Truth...")
    
    try:
        rows = sheets_etl.fetch_all_data()
    except Exception as e:
        logger.error(f"❌ [CRITICAL] Failed to reach Google Sheets during startup: {e}")
        logger.warning("⚠️ Application will start with existing local data (if any). Sync will retry on the next write.")
        return

    if not rows:
        logger.info("ℹ️ [STARTUP] No historical data found in Google Sheets. Local cache remains empty.")
        return

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Atomic transaction for recovery
            cursor.execute("BEGIN TRANSACTION")
            try:
                # Clear existing local cache for specific user (or all if recovering fresh)
                cursor.execute("DELETE FROM expenses")
                
                # Batch insert recovered rows
                data_to_insert = [
                    (r['id'], r['user_id'], r['date'], r['amount'], r['category'], r['description'])
                    for r in rows
                ]
                cursor.executemany('''
                    INSERT INTO expenses (id, user_id, date, amount, category, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', data_to_insert)
                
                conn.commit()
                logger.info(f"✅ [SUCCESS] Hot-cache synchronized: {len(rows)} records restored from Sheets.")
            except Exception as e:
                cursor.execute("ROLLBACK")
                logger.error(f"❌ [DB_ERROR] Failed to commit restored data to SQLite: {e}")
                raise
    except Exception as e:
        logger.error(f"❌ [SYNC_FAIL] Database recovery failed: {e}")


if __name__ == "__main__":
    # verification block
    print("--- Starting Database Verification ---")

    # 1. Initialize DB
    print("Initializing database...")
    init_db()

    # 2. Add a test expense
    test_user_id = 123456789
    print(f"Adding test expense for user {test_user_id}...")
    add_expense(test_user_id, 50.0, "Food", "Pizza verification")
    add_expense(test_user_id, 30.0, "Transport", "Taxi")

    # 3. Retrieve and display expenses
    print(f"Fetching recent expenses for user {test_user_id}...")
    expenses = get_recent_expenses(user_id=test_user_id)

    if expenses:
        print("Success! Found expenses:")
        for exp in expenses:
            print(exp)

    # 4. Check monthly summary
    summary = get_monthly_summary(test_user_id)
    print(f"Monthly summary: {summary}")

    # 5. Check category totals
    print("Category totals:")
    totals = get_category_totals(test_user_id)
    print(totals)

    print("--- Verification Complete ---")

