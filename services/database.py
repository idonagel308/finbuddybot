import sqlite3
import math
import logging
import threading
import os
from datetime import datetime
from contextlib import contextmanager
try:
    import services.sheets_etl as sheets_etl
except ImportError:
    sheets_etl = None
    logging.warning("Sheets ETL not available. Sync disabled.")


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = "fintech.db"

# Validation constants
MAX_AMOUNT = 1_000_000  # Maximum single expense amount
MAX_DESCRIPTION_LENGTH = 200
ALLOWED_CATEGORIES = {
    'Housing', 'Food', 'Transport', 'Entertainment',
    'Shopping', 'Health', 'Education', 'Financial', 'Other',
    'Salary', 'Investment', 'Gift'
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


def backup_db():
    """Creates a local hot-backup of the database using the official sqlite3 backup API.
    Handles OS-level locks gracefully to prevent crashing on restricted environments."""
    if not os.path.exists(DB_NAME) or os.path.getsize(DB_NAME) == 0:
        return

    backup_name = f"{DB_NAME}.bak"
    try:
        import sqlite3
        # Explicit disconnect attempt for Windows stability
        close_connection()
        
        src = sqlite3.connect(DB_NAME)
        dst = sqlite3.connect(backup_name)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        logger.info(f"Database hot-backup created: {backup_name}")
    except (PermissionError, sqlite3.OperationalError):
        logger.warning(f"Skipping database backup: File is currently locked by another process.")
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")

def run_background_task(target, *args, **kwargs):
    """Safely runs a task in a background thread without affecting the main process."""
    def wrapper():
        try:
            target(*args, **kwargs)
        except Exception as e:
            logger.error(f"Background task {target.__name__} failed: {e}")

    threading.Thread(target=wrapper, daemon=True).start()

def sync_from_sheets(user_id: int = None, limit: int = 100):
    """
    Syncs the latest expenses from Google Sheets into the SQLite database.
    This acts as a cold-start recovery mechanism.
    """
    if not sheets_etl:
        logger.warning("sheets_etl module not loaded. Skipping Sheets sync.")
        return
        
    try:
        sheet = sheets_etl._get_sheet()
        if not sheet:
            logger.warning("Could not get sheet for sync.")
            return
            
        # Get all records, ignoring the header row
        records = sheet.get_all_values()[1:]
        if not records:
            return
            
        # Optional: filter by user and slice
        if user_id:
            records = [r for r in records if len(r) > 1 and str(r[1]) == str(user_id)]
            
        # Take the most recent `limit` rows (assuming appended at the bottom)
        records = records[-limit:]
        
        with get_connection() as conn:
            cursor = conn.cursor()
            for row in records:
                try:
                    # Expected: ID, User ID, Date, Amount, Category, Description
                    if len(row) < 5:
                        continue
                        
                    # Sheet might not have the ID if manual, but let's just insert
                    r_uid = int(row[1])
                    r_date = row[2]
                    r_amt = float(row[3].replace(',', '').replace('₪', '').strip())
                    r_cat = row[4]
                    r_desc = row[5] if len(row) > 5 else ""
                    
                    # Insert if it doesn't already exist (rough deduplication)
                    cursor.execute('''
                        SELECT 1 FROM expenses 
                        WHERE user_id = ? AND date = ? AND amount = ? AND category = ?
                    ''', (r_uid, r_date, r_amt, r_cat))
                    if not cursor.fetchone():
                        cursor.execute('''
                            INSERT INTO expenses (user_id, date, amount, category, type, description)
                            VALUES (?, ?, ?, ?, 'expense', ?)
                        ''', (r_uid, r_date, r_amt, r_cat, r_desc))
                except Exception as row_error:
                    logger.warning(f"Failed to sync row from sheets: {row} - {row_error}")
            
            conn.commit()
            logger.info(f"Successfully synced up to {len(records)} recent expenses from Sheets.")
            
    except Exception as e:
        logger.error(f"Failed to sync from sheets: {e}")


_local = threading.local()


def init_db():
    """Initializes the SQLite database. Creates a backup first if the file exists."""
    backup_db()
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
                    type TEXT NOT NULL DEFAULT 'expense',
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
                    language TEXT DEFAULT 'English',
                    additional_info TEXT
                )
            ''')

            # 5. Insights Table (Phase 3)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS insights (
                    user_id BIGINT,
                    year INTEGER,
                    month INTEGER,
                    content TEXT,
                    timestamp TEXT,
                    PRIMARY KEY (user_id, year, month)
                )
            ''')

            # 6. User Dashboard Settings (Phase 3)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id BIGINT PRIMARY KEY,
                    theme TEXT DEFAULT 'dark',
                    layout TEXT,
                    budget_target REAL DEFAULT 0,
                    financial_goal TEXT,
                    language TEXT DEFAULT 'English',
                    accent_color TEXT DEFAULT 'indigo'
                )
            ''')

            # Migration helpers (safe for existing installations)
            try: cursor.execute("ALTER TABLE expenses ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'")
            except: pass
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN yearly_income REAL")
            except: pass
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN currency TEXT DEFAULT 'NIS'")
            except: pass
            try: cursor.execute("ALTER TABLE profiles ADD COLUMN language TEXT DEFAULT 'English'")
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


def add_expense(user_id: int, amount: float, category: str, description: str = "", transaction_type: str = "expense"):
    """Adds a new expense or income to SQLite."""
    _validate_user_id(user_id)
    _validate_expense(amount, category, description)
    if description:
        description = description[:MAX_DESCRIPTION_LENGTH].strip()

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            date_str = datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO expenses (user_id, date, amount, category, type, description)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, date_str, amount, category, transaction_type, description))
            
            inserted_id = cursor.lastrowid
            conn.commit()
            
            logger.info(f"Added {transaction_type} {inserted_id} for user {user_id}")
            
            # Mirror to Sheets in background
            if sheets_etl:
                run_background_task(sheets_etl.append_expense, inserted_id, user_id, date_str, amount, category, description)
            
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
            query = "SELECT id, date, amount, category, description, type FROM expenses"
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
            
            # total expenses
            cursor.execute('''
                SELECT SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND type = 'expense' AND date >= ? AND date < ?
            ''', (user_id, start, end))
            res_exp = cursor.fetchone()
            total_exp = res_exp[0] if res_exp and res_exp[0] else 0.0

            # total income
            cursor.execute('''
                SELECT SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND type = 'income' AND date >= ? AND date < ?
            ''', (user_id, start, end))
            res_inc = cursor.fetchone()
            total_inc = res_inc[0] if res_inc and res_inc[0] else 0.0

            return total_exp, total_inc
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
                SELECT CAST(strftime('%m', date) AS INTEGER) as month, 
                       SUM(CASE WHEN type = 'expense' THEN amount ELSE -amount END) as net_total
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
                SELECT id, date, amount, category, description, type
                FROM expenses 
                WHERE user_id = ? AND date >= ? AND date < ?
                ORDER BY date DESC
            ''', (user_id, start, end))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error fetching monthly expenses: {e}")
        return []


def get_category_totals(user_id: int, year: int = None, month: int = None):
    """Calculates category totals for a month from cache.
    
    Returns a nested dict: {category: {"expenses": float, "income": float}}
    Use get_expense_totals() for the simpler flat format needed by charts/insights.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            start, end = _month_range(year, month)
            cursor.execute('''
                SELECT category, 
                       SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END) as expenses,
                       SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END) as income
                FROM expenses 
                WHERE user_id = ? AND date >= ? AND date < ?
                GROUP BY category
            ''', (user_id, start, end))
            return {row[0]: {"expenses": row[1], "income": row[2]} for row in cursor.fetchall()}
    except Exception as e:
        logger.error(f"Error fetching category totals: {e}")
        return {}


def get_expense_totals(user_id: int, year: int = None, month: int = None) -> dict:
    """Returns a flat {category: amount} dict of EXPENSE-ONLY spending for a month.

    This is the safe, consumer-friendly format used by:
    - Pie chart generation
    - AI insights generation
    - The /chart REST API endpoint

    It wraps get_category_totals() so that changes to the internal nested
    structure never silently break these downstream consumers again.
    """
    nested = get_category_totals(user_id, year, month)
    flat = {}
    for cat, vals in nested.items():
        if isinstance(vals, dict):
            amount = vals.get("expenses", 0) or 0
        else:
            # Safety: handle legacy flat format gracefully
            amount = float(vals) if vals else 0
        if amount > 0:
            flat[cat] = round(amount, 2)
    return flat


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
                # Mirror to Sheets in background
                if sheets_etl:
                    run_background_task(sheets_etl.delete_expense, expense_id)
                
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


def set_profile(user_id: int, age: int, yearly_income: float, currency: str = 'NIS', language: str = 'English', additional_info: str = ""):
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
                INSERT OR REPLACE INTO profiles (user_id, age, yearly_income, currency, language, additional_info) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, age, yearly_income, currency, language, additional_info))
            conn.commit()
    except Exception as e:
        logger.error(f"Error setting profile: {e}")
        raise


def get_profile(user_id: int) -> dict | None:
    """Returns profile from cache."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT age, yearly_income, currency, language, additional_info FROM profiles WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'age': row[0], 'yearly_income': row[1] or 0.0,
                    'currency': row[2] or 'NIS', 'language': row[3] or 'English',
                    'additional_info': row[4] or ""
                }
            return None
    except Exception as e:
        logger.error(f"Error fetching profile: {e}")
        return None


# ── AI Insights Persistence ──

def save_insight(user_id: int, year: int, month: int, content: str):
    """Saves a generated AI insight to the database."""
    _validate_user_id(user_id)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            ts = datetime.now().isoformat()
            cursor.execute('''
                INSERT OR REPLACE INTO insights (user_id, year, month, content, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, year, month, content, ts))
            conn.commit()
            logger.info(f"Saved AI insight for user {user_id} ({year}-{month:02})")
    except Exception as e:
        logger.error(f"Error saving insight: {e}")


def get_insight(user_id: int, year: int, month: int) -> str | None:
    """Retrieves a cached AI insight from the database."""
    _validate_user_id(user_id)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT content FROM insights 
                WHERE user_id = ? AND year = ? AND month = ?
            ''', (user_id, year, month))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"Error fetching insight: {e}")
        return None


# ── User Dashboard & Pulse Aggregations (Phase 3) ──



# ── User Dashboard Settings ──

def save_user_settings(user_id: int, theme: str = None, layout: str = None, budget_target: float = None, financial_goal: str = None, language: str = None, accent_color: str = None):
    """Saves or updates user-specific dashboard preferences."""
    _validate_user_id(user_id)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Perform a multi-step update to preserve existing values if some are passed as None
            cursor.execute('''
                INSERT INTO user_settings (user_id, theme, layout, budget_target, financial_goal, language, accent_color)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    theme = COALESCE(?, theme),
                    layout = COALESCE(?, layout),
                    budget_target = COALESCE(?, budget_target),
                    financial_goal = COALESCE(?, financial_goal),
                    language = COALESCE(?, language),
                    accent_color = COALESCE(?, accent_color)
            ''', (user_id, theme, layout, budget_target, financial_goal, language, accent_color,
                  theme, layout, budget_target, financial_goal, language, accent_color))
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving user settings: {e}")

def get_user_settings(user_id: int) -> dict:
    """Retrieves user-specific dashboard preferences as a dictionary."""
    _validate_user_id(user_id)
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT theme, layout, budget_target, financial_goal, language, accent_color FROM user_settings WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "theme": row[0],
                    "layout": row[1],
                    "budget_target": row[2],
                    "financial_goal": row[3],
                    "language": row[4],
                    "accent_color": row[5]
                }
            return {}
    except Exception as e:
        logger.error(f"Error fetching user settings: {e}")
        return {}


def get_daily_aggregation(user_id: int, year: int = None, month: int = None):
    """
    Returns day-by-day cumulative totals for the Pulse chart.
    Returns: { "labels": [...], "income": [...], "expenses": [...] }
    """
    _validate_user_id(user_id)
    start, end = _month_range(year, month)
    
    # Calculate days in month
    import calendar
    dt_start = datetime.fromisoformat(start)
    _, last_day = calendar.monthrange(dt_start.year, dt_start.month)
    
    labels = [str(d) for d in range(1, last_day + 1)]
    income_series = [0.0] * last_day
    expense_series = [0.0] * last_day

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch sums per day
            cursor.execute('''
                SELECT CAST(strftime('%d', date) AS INTEGER) as day, type, SUM(amount)
                FROM expenses
                WHERE user_id = ? AND date >= ? AND date < ?
                GROUP BY day, type
            ''', (user_id, start, end))
            
            for day, t_type, total in cursor.fetchall():
                day_idx = day - 1
                if day_idx < last_day:
                    if t_type == 'income':
                        income_series[day_idx] = total
                    else:
                        expense_series[day_idx] = total
            
            # Convert to cumulative sums
            curr_inc = 0.0
            curr_exp = 0.0
            for i in range(last_day):
                curr_inc += income_series[i]
                curr_exp += expense_series[i]
                income_series[i] = round(curr_inc, 2)
                expense_series[i] = round(curr_exp, 2)
                
            return {
                "labels": labels,
                "income": income_series,
                "expenses": expense_series
            }
            
    except Exception as e:
        logger.error(f"Error in daily aggregation: {e}")
        return {"labels": [], "income": [], "expenses": []}


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
                'SELECT id, user_id, date, amount, category, type, description FROM expenses WHERE user_id = ? ORDER BY date ASC',
                (user_id,)
            )
            rows = cursor.fetchall()
            
        # Format for gspread
        formatted = []
        for r in rows:
            formatted.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6] or ""])
            
        # Background thread so the Telegram UI doesn't hang
        if sheets_etl:
            run_background_task(sheets_etl.rewrite_user_expenses, user_id, formatted)
        else:
            logger.info(f"Skipping wholesale sync for user {user_id} (Sheets ETL disabled)")
        logger.info(f"Triggered background wholesale sync for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to initiate wholesale sync: {e}")

def sync_from_sheets():
    """
    Recovers the local SQLite cache from Google Sheets.
    Senior Developer Note: This is an idempotent 'Cold Start' recovery logic.
    """
    logger.info("Initializing Cold Start Recovery from Sheets...")
    backup_db()  # Safety first
    try:
        if not sheets_etl:
            logger.info("Sync from Sheets skipped (ETL module missing or disabled).")
            return
        
        sheets_data = sheets_etl.fetch_all_data()
        if not sheets_data:
            logger.info("Cloud recovery returned no data. aborting wipe to preserve local truth.")
            return

        # Integrity Check: If we have local data, but cloud is suspiciously small, abort.
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM expenses")
            local_count = cursor.fetchone()[0]
            
            if local_count > 10 and len(sheets_data) < (local_count / 2):
                logger.warning(f"Cloud data ({len(sheets_data)}) is significantly smaller than local data ({local_count}). Aborting recovery to prevent data loss.")
                return

        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Wipe local cache to enforce Sheets as the single source of truth
            cursor.execute('DELETE FROM expenses')
            
            # Batch insert
            insert_data = [
                (d['id'], d['user_id'], d['date'], d['amount'], d['category'], d.get('type', 'expense'), d['description'])
                for d in sheets_data
            ]
            cursor.executemany('''
                INSERT OR REPLACE INTO expenses (id, user_id, date, amount, category, type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', insert_data)
            conn.commit()
            
        logger.info(f"Cold Start complete. Synced {len(insert_data)} expenses from Sheets.")
    except Exception as e:
        logger.error(f"Failed to sync from Sheets during Cold Start: {e}")


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

