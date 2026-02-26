
import os
import gspread
import google.auth
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def diagnostic():
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    print(f"Checking Sheet ID: {sheet_id}")
    
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        client = gspread.authorize(creds)
        
        try:
            doc = client.open_by_key(sheet_id)
            print("✅ Successfully opened the Spreadsheet.")
            
            worksheets = doc.worksheets()
            titles = [ws.title for ws in worksheets]
            print(f"Found {len(worksheets)} worksheet(s): {titles}")
                
            if "Expenses" not in titles:
                print("❌ 'Expenses' worksheet NOT FOUND. Attempting to create it...")
                # Create with headers
                new_ws = doc.add_worksheet(title="Expenses", rows="1000", cols="20")
                headers = ["ID", "User ID", "Date", "Amount", "Category", "Description"]
                new_ws.append_row(headers)
                print("✅ 'Expenses' worksheet created with headers.")
            else:
                print("✅ 'Expenses' worksheet exists.")
                ws = doc.worksheet("Expenses")
                vals = ws.get_all_values()
                print(f"Current data rows: {max(0, len(vals)-1)}")
                if len(vals) == 0 or "ID" not in vals[0][0].upper():
                     print("⚠️ Headers missing or corrupt. Re-applying headers.")
                     headers = ["ID", "User ID", "Date", "Amount", "Category", "Description"]
                     ws.insert_row(headers, 1)

        except gspread.exceptions.SpreadsheetNotFound:
            print("❌ Spreadsheet document NOT FOUND. Please check the ID or permissions.")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    diagnostic()
