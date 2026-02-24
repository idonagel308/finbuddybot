import os
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# Define the scopes for Google Sheets and Drive APIs
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def append_expense_to_sheet(expense_dict: dict):
    """
    Appends a single expense record to the configured Google Sheet.
    This is designed to be run as a background task.
    
    Expected keys in expense_dict:
      - 'id': (int/str) ID of the expense (e.g., from DB)
      - 'user_id': (int) Telegram user ID
      - 'date': (str) Date of the transaction
      - 'amount': (float) The expense amount
      - 'category': (str) The category category
      - 'description': (str) Optional details
    """
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.warning("GOOGLE_SHEET_ID not found in environment variables. Skipping Sheets ETL.")
        return

    # Check for credentials
    creds_path = "credentials.json"
    if not os.path.exists(creds_path):
        logger.warning(f"Google credentials file not found at {creds_path}. Skipping Sheets ETL.")
        return

    try:
        # Authenticate with Google
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # Open the spreadsheet and select the first worksheet
        sheet = client.open_by_key(sheet_id).sheet1
        
        # Prepare the row data
        # Adjust order as needed for your spreadsheet columns
        # E.g.: [Expense ID, User ID, Date, Amount, Category, Description, Sync Timestamp]
        row_data = [
            expense_dict.get("id", ""),
            expense_dict.get("user_id", ""),
            expense_dict.get("date", ""),
            expense_dict.get("amount", ""),
            expense_dict.get("category", ""),
            expense_dict.get("description", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]
        
        # Append the row
        sheet.append_row(row_data)
        logger.info(f"Successfully synced expense {expense_dict.get('id')} to Google Sheets.")
        
    except gspread.exceptions.APIError as e:
        logger.error(f"Google Sheets API Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during Sheets ETL sync: {type(e).__name__} - {e}")
