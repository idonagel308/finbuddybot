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

def _get_worksheet(title="Expenses", headers=None):
    """Returns the authenticated Worksheet. Creates it if missing."""
    global _cached_sheet, _sheet_cache_time

    cache_key = f"{title}_sheet"
    if not hasattr(_get_worksheet, "cache"):
        _get_worksheet.cache = {}
        _get_worksheet.cache_time = {}

    if cache_key in _get_worksheet.cache and (time.time() - _get_worksheet.cache_time[cache_key]) < SHEET_CACHE_TTL:
        return _get_worksheet.cache[cache_key]

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("Missing GOOGLE_SHEET_ID")
        return None

    try:
        creds, project = google.auth.default(scopes=SCOPES)
        client = gspread.authorize(creds)
        doc = client.open_by_key(sheet_id)
        
        try:
            sheet = doc.worksheet(title)
            # Check if headers exist, add them if empty
            if not sheet.row_values(1):
                if not headers:
                    if title == "Expenses":
                        headers = ["Transaction ID", "User Account ID", "Transaction Date", "Amount (NIS)", "Action Category", "Description / Notes"]
                    elif title == "Profiles":
                        headers = ["User ID", "Age", "Yearly Income", "Currency", "Language", "Additional Info"]
                    elif title == "Settings":
                        headers = ["User ID", "Theme", "Layout", "Budget Target", "Financial Goal", "Language", "Accent Color"]
                if headers:
                    sheet.append_row(headers)
                    logger.info(f"Added descriptive headers to existing '{title}' worksheet.")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"'{title}' worksheet not found. Creating it...")
            sheet = doc.add_worksheet(title=title, rows="1000", cols="20")
            if not headers:
                if title == "Expenses":
                    headers = ["Transaction ID", "User Account ID", "Transaction Date", "Amount (NIS)", "Action Category", "Description / Notes"]
                elif title == "Profiles":
                    headers = ["User ID", "Age", "Yearly Income", "Currency", "Language", "Additional Info"]
                elif title == "Settings":
                    headers = ["User ID", "Theme", "Layout", "Budget Target", "Financial Goal", "Language", "Accent Color"]
            if headers:
                sheet.append_row(headers)
            logger.info(f"Created '{title}' worksheet with descriptive headers.")
        _get_worksheet.cache_time[cache_key] = time.time()
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
    sheet = _get_worksheet("Expenses")
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
    sheet = _get_worksheet("Expenses")
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
    """Retrieves all rows from the Expenses sheet for database recovery with retry logic."""
    sheet = _get_worksheet("Expenses")
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
    sheet = _get_worksheet("Expenses")
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

@_retry
def rewrite_all_expenses(all_rows: list):
    """
    Replaces ALL expenses in the sheet with the provided master list.
    Used during application shutdown to guarantee the Google Sheet perfectly
    mirrors the local SQLite truth, removing any manual garbage inserted in Sheets.
    """
    sheet = _get_worksheet("Expenses")
    if not sheet: return

    headers = ["Transaction ID", "User Account ID", "Transaction Date", "Amount (NIS)", "Action Category", "Description / Notes"]
    
    # We always write the headers first
    final_rows = [headers]
    for r in all_rows:
        final_rows.append(list(r))
        
    sheet.clear()
    
    if final_rows:
        sheet.update(values=final_rows, range_name='A1')
        
    logger.info(f"Global sync complete. Wiped sheet and wrote {len(all_rows)} exact local rows.")

@_retry
def fetch_all_profiles():
    """Retrieves all profiles for database recovery."""
    sheet = _get_worksheet("Profiles")
    if not sheet: return []
    
    all_vals = sheet.get_all_values()
    if not all_vals or len(all_vals) <= 1: return []
    
    cleaned = []
    for r in all_vals[1:]:
        if len(r) < 6: continue
        try:
            cleaned.append({
                'user_id': int(r[0]),
                'age': int(r[1]) if r[1] else None,
                'yearly_income': float(r[2]) if r[2] else 0.0,
                'currency': str(r[3]),
                'language': str(r[4]),
                'additional_info': str(r[5])
            })
        except ValueError:
            continue
    return cleaned

@_retry
def rewrite_profiles(profiles_data: list):
    """Rewrites the entire Profiles worksheet."""
    sheet = _get_worksheet("Profiles")
    if not sheet: return
    
    headers = ["User ID", "Age", "Yearly Income", "Currency", "Language", "Additional Info"]
    rows = [headers]
    for p in profiles_data:
        rows.append([p[0], p[1], p[2], p[3], p[4], p[5]])
        
    sheet.clear()
    if rows:
        sheet.update(values=rows, range_name='A1')
    logger.info(f"Wholesale sync of {len(profiles_data)} profiles to Sheets complete.")

@_retry
def fetch_all_settings():
    """Retrieves all user settings for database recovery."""
    sheet = _get_worksheet("Settings")
    if not sheet: return []
    
    all_vals = sheet.get_all_values()
    if not all_vals or len(all_vals) <= 1: return []
    
    cleaned = []
    for r in all_vals[1:]:
        if len(r) < 7: continue
        try:
            cleaned.append({
                'user_id': int(r[0]),
                'theme': str(r[1]) if r[1] else None,
                'layout': str(r[2]) if r[2] else None,
                'budget_target': float(r[3]) if r[3] else None,
                'financial_goal': str(r[4]) if r[4] else None,
                'language': str(r[5]) if r[5] else None,
                'accent_color': str(r[6]) if r[6] else None
            })
        except ValueError:
            continue
    return cleaned

@_retry
def rewrite_settings(settings_data: list):
    """Rewrites the entire Settings worksheet."""
    sheet = _get_worksheet("Settings")
    if not sheet: return
    
    headers = ["User ID", "Theme", "Layout", "Budget Target", "Financial Goal", "Language", "Accent Color"]
    rows = [headers]
    for s in settings_data:
        rows.append([s[0], s[1], s[2], s[3], s[4], s[5], s[6]])
        
    sheet.clear()
    if rows:
        sheet.update(values=rows, range_name='A1')
    logger.info(f"Wholesale sync of {len(settings_data)} settings to Sheets complete.")

