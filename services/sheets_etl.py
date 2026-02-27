import os
import time
import logging
import gspread
import google.auth
from google.auth.exceptions import DefaultCredentialsError
from gspread_formatting import (
    cellFormat, 
    format_cell_range
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
MAX_RETRIES = 3
RETRY_DELAY = 2  # Seconds

# Global cache
_cached_sheet = None
_sheet_cache_time = 0
SHEET_CACHE_TTL = 300

def _retry(func):
    """Decorator for retrying Gspread calls on rate limits or transient errors."""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except gspread.exceptions.APIError as e:
                # Handle 429 Rate Limit
                if '429' in str(e):
                    wait = RETRY_DELAY * (2 ** attempt)
                    logger.warning(f"Sheets API Rate Limit. Waiting {wait}s...")
                    time.sleep(wait)
                    last_exception = e
                    continue
                raise
            except Exception as e:
                logger.error(f"Transient error in Sheets API: {e}")
                time.sleep(1)
                last_exception = e
        raise last_exception
    return wrapper

def _get_sheet():
    """Returns the authenticated Worksheet using ADC (Application Default Credentials)."""
    global _cached_sheet, _sheet_cache_time

    if _cached_sheet and (time.time() - _sheet_cache_time) < SHEET_CACHE_TTL:
        return _cached_sheet

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("Missing GOOGLE_SHEET_ID")
        return None

    try:
        # SECURE AUTH: Use credentials from the environment (ADC)
        # In Cloud Run, this uses the attached Service Account.
        # Locally, this uses GOOGLE_APPLICATION_CREDENTIALS env var.
        creds, project = google.auth.default(scopes=SCOPES)
        client = gspread.authorize(creds)
        doc = client.open_by_key(sheet_id)
        
        # Auto-Heal: Ensure 'Expenses' worksheet exists
        try:
            sheet = doc.worksheet("Expenses")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("'Expenses' worksheet not found. Creating it...")
            sheet = doc.add_worksheet(title="Expenses", rows="1000", cols="20")
            headers = ["ID", "User ID", "Date", "Amount", "Category", "Description"]
            sheet.append_row(headers)
            logger.info("Created 'Expenses' worksheet with default headers.")

        _cached_sheet = sheet
        _sheet_cache_time = time.time()
        return sheet
    except DefaultCredentialsError:
        logger.error("No Google Application Default Credentials found.")
        return None
    except Exception as e:
        logger.error(f"Auth/Connection error: {e}")
        return None

def _is_hebrew(text: str) -> bool:
    """Detects if text contains Hebrew characters."""
    return any("\u0590" <= char <= "\u05FF" for char in text)

@_retry
def append_expense(expense_id, user_id, date, amount, category, description):
    """Appends an expense to the sheet and applies formatting with retry logic."""
    sheet = _get_sheet()
    if not sheet: return

    safe_desc = str(description)
    if safe_desc.startswith(('=', '+', '-', '@')):
        safe_desc = "'" + safe_desc

    row_data = [expense_id, user_id, date, amount, category, safe_desc]
    
    res = sheet.append_row(row_data, value_input_option='USER_ENTERED')
    
    # Determine row for formatting
    updated_range = res.get('updates', {}).get('updatedRange', '')
    if '!' in updated_range:
        try:
            row_num = int(''.join(filter(str.isdigit, updated_range.split('!')[1].split(':')[0])))
            fmt = cellFormat(wrapStrategy='WRAP')
            if _is_hebrew(safe_desc):
                fmt.textDirection = 'RIGHT_TO_LEFT'
            format_cell_range(sheet, f"E{row_num}:F{row_num}", fmt)
        except (ValueError, IndexError): pass

@_retry
def delete_expense(expense_id):
    """Deletes an expense from the sheet with retry logic."""
    sheet = _get_sheet()
    if not sheet: return

    ids = sheet.col_values(1)
    try:
        row_index = ids.index(str(expense_id)) + 1
        sheet.delete_rows(row_index)
        logger.info(f"Deleted row with ID {expense_id} from Sheets.")
    except ValueError:
        logger.warning(f"ID {expense_id} not found in Sheets.")

@_retry
def fetch_all_data():
    """Retrieves all rows from the sheet for database recovery with retry logic."""
    sheet = _get_sheet()
    if not sheet: return []
    
    all_vals = sheet.get_all_values()
    if not all_vals: return []
    
    header = all_vals[0]
    rows = all_vals[1:] if "ID" in str(header[0]).upper() else all_vals
    
    cleaned = []
    for r in rows:
        if len(r) < 5: continue
        try:
            cleaned.append({
                'id': int(r[0]),
                'user_id': int(r[1]),
                'date': str(r[2]),
                'amount': float(r[3]),
                'category': str(r[4]),
                'description': str(r[5]) if len(r) > 5 else ""
            })
        except (ValueError, IndexError):
            continue
    return cleaned

@_retry
def rewrite_user_expenses(user_id: int, new_rows: list):
    """
    Replaces all expenses for a specific user in the sheet.
    Used for mass-deletions to keep the sheet in perfect sync with the SQLite cache.
    """
    sheet = _get_sheet()
    if not sheet: return

    # Get all current data to preserve any other users or headers
    all_vals = sheet.get_all_values()
    if not all_vals: return

    header = all_vals[0]
    
    # Filter OUT the rows belonging to this user
    retained_rows = [header]
    for row in all_vals[1:]:
        if len(row) > 1 and str(row[1]) != str(user_id):
            retained_rows.append(row)
            
    # Append the fresh truth for this user from the local DB
    for r in new_rows:
        retained_rows.append(list(r))
        
    sheet.clear()
    
    if retained_rows:
        sheet.update(values=retained_rows, range_name='A1')
        
    logger.info(f"Rewrote sheet. Maintained {len(retained_rows)-len(new_rows)-1} foreign rows, added {len(new_rows)} fresh rows for user {user_id}.")

