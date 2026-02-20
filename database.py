import sqlite3
import logging
from datetime import datetime
from contextlib import contextmanager

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
    """Context manager for safe database connections."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for concurrency
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        if conn:
            conn.close()


def init_db():
    """Initializes the database by creating the expenses table if it doesn't exist."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount > 0),
                    category TEXT NOT NULL,
                    description TEXT
                )
            ''')

            # Create index for faster user queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_expenses_user_date 
                ON expenses(user_id, date)
            ''')

            # Budget table (one row per user)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS budgets (
                    user_id INTEGER PRIMARY KEY,
                    amount REAL NOT NULL CHECK(amount > 0)
                )
            ''')

            # Profiles table (age and monthly wage)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id INTEGER PRIMARY KEY,
                    age INTEGER,
                    wage REAL
                )
            ''')

            conn.commit()
            logger.info("Database initialized and tables checked.")
    except sqlite3.Error as e:
        logger.error(f"Error initializing database: {e}")


def _validate_expense(amount: float, category: str, description: str = ""):
    """Validates expense data before insertion."""
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError(f"Amount must be a positive number, got: {type(amount)}")
    if amount > MAX_AMOUNT:
        raise ValueError(f"Amount exceeds maximum allowed ({MAX_AMOUNT})")
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Invalid category: {category}")
    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters")


def add_expense(user_id: int, amount: float, category: str, description: str = ""):
    """
    Adds a new expense to the database.

    Args:
        user_id (int): The user ID.
        amount (float): The cost of the expense (must be positive).
        category (str): The category (must be from ALLOWED_CATEGORIES).
        description (str): Optional details about the expense.

    Raises:
        ValueError: If input validation fails.
    """
    # Validate inputs
    _validate_expense(amount, category, description)

    # Sanitize description
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

            conn.commit()
            logger.info(f"Added expense for user {user_id}: category={category}")
    except sqlite3.Error as e:
        logger.error(f"Error adding expense: {e}")
        raise


def get_recent_expenses(user_id: int = None, limit: int = 5):
    """
    Retrieves the most recent expenses.

    Args:
        user_id (int, optional): Filter by user ID. If None, returns all.
        limit (int): Number of expenses to retrieve (max 50).

    Returns:
        list: A list of tuples containing expense records.
    """
    # Cap limit to prevent abuse
    limit = min(max(1, limit), 50)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT id, date, amount, category, description FROM expenses"
            params = []

            if user_id is not None:  # Fixed: was `if user_id` which fails for user_id=0
                query += " WHERE user_id = ?"
                params.append(user_id)

            query += " ORDER BY date DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))

            rows = cursor.fetchall()
            return rows
    except sqlite3.Error as e:
        logger.error(f"Error fetching expenses: {e}")
        return []


def get_monthly_summary(user_id: int):
    """
    Calculates total expenses for the current month for a specific user.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            current_month = datetime.now().strftime('%Y-%m')

            cursor.execute('''
                SELECT SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND date LIKE ?
            ''', (user_id, f'{current_month}%'))

            result = cursor.fetchone()
            return result[0] if result[0] else 0.0
    except sqlite3.Error as e:
        logger.error(f"Error fetching summary: {e}")
        return 0.0


def get_monthly_expenses(user_id: int):
    """
    Retrieves all expenses for the current month for a specific user.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            current_month = datetime.now().strftime('%Y-%m')

            cursor.execute('''
                SELECT id, date, amount, category, description 
                FROM expenses 
                WHERE user_id = ? AND date LIKE ?
                ORDER BY date DESC
            ''', (user_id, f'{current_month}%'))

            rows = cursor.fetchall()
            return rows
    except sqlite3.Error as e:
        logger.error(f"Error fetching monthly expenses: {e}")
        return []


def get_category_totals(user_id: int):
    """
    Returns a dictionary of {category: total_amount} for the current month.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            current_month = datetime.now().strftime('%Y-%m')

            cursor.execute('''
                SELECT category, SUM(amount) 
                FROM expenses 
                WHERE user_id = ? AND date LIKE ?
                GROUP BY category
            ''', (user_id, f'{current_month}%'))

            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
    except sqlite3.Error as e:
        logger.error(f"Error fetching category totals: {e}")
        return {}


def delete_expense(user_id: int, expense_id: int) -> bool:
    """Deletes an expense only if it belongs to the given user."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM expenses WHERE id = ? AND user_id = ?',
                (expense_id, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Error deleting expense: {e}")
        return False


def get_last_expense_id(user_id: int) -> int | None:
    """Returns the ID of the most recent expense for a user."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM expenses WHERE user_id = ? ORDER BY date DESC LIMIT 1',
                (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except sqlite3.Error as e:
        logger.error(f"Error fetching last expense: {e}")
        return None


def export_expenses_csv(user_id: int) -> str:
    """Returns all expenses for a user as a CSV string."""
    import csv
    import io

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
    except sqlite3.Error as e:
        logger.error(f"Error exporting CSV: {e}")
        return ""


def set_budget(user_id: int, amount: float):
    """Sets or updates the monthly budget for a user."""
    if amount <= 0 or amount > MAX_AMOUNT:
        raise ValueError(f"Budget must be between 0 and {MAX_AMOUNT}")
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO budgets (user_id, amount) VALUES (?, ?)',
                (user_id, amount)
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error setting budget: {e}")
        raise


def get_budget(user_id: int) -> float | None:
    """Returns the budget for a user, or None if not set."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT amount FROM budgets WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            return row[0] if row else None
    except sqlite3.Error as e:
        logger.error(f"Error fetching budget: {e}")
        return None


def set_profile(user_id: int, age: int, wage: float):
    """Sets or updates the user profile."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO profiles (user_id, age, wage) VALUES (?, ?, ?)',
                (user_id, age, wage)
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error setting profile: {e}")
        raise


def get_profile(user_id: int) -> dict | None:
    """Returns the user profile as a dict."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT age, wage FROM profiles WHERE user_id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return {'age': row[0], 'wage': row[1]}
            return None
    except sqlite3.Error as e:
        logger.error(f"Error fetching profile: {e}")
        return None


def delete_all_expenses(user_id: int) -> int:
    """Deletes ALL expenses for a given user. Returns the number of deleted rows."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM expenses WHERE user_id = ?', (user_id,))
            conn.commit()
            count = cursor.rowcount
            logger.info(f"Deleted {count} expenses for user {user_id}")
            return count
    except sqlite3.Error as e:
        logger.error(f"Error deleting all expenses: {e}")
        return 0


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

