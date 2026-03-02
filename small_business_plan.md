This guide outlines the technical steps to transform FinTechBot into a powerful tool for small businesses, while keeping it simple for personal users.

## 0. Account Type Onboarding (`handlers/onboarding.py`)
Users should choose their focus early to get the right interface.

- **Initial Setup:** During the `/start` or onboarding flow, present two buttons: `💼 Small Business` and `👤 Personal`.
- **Profile Storage:** Update the profile schema (in `firestore_service.py` and `database.py`) to include `account_type`.
- **Conditional Interface:**
    - **Personal:** Classic simplified dashboard, only past-tense logging.
    - **Small Business:** Enables "Future Tracking", "Cash Flow Forecasting", and "Business Analytics" on the web dashboard.

## 1. Schema Enhancement (`services/database.py`)
Small businesses need to track not just what happened, but what *will* happen.

- **Storage Updates:**
    - Modify the `expenses` table to include a `due_date` (DATETIME) and a `status` (TEXT: 'completed', 'planned').
    - Update `init_db` to handle these migrations safely.
- **Logic Updates:**
    - Update `add_expense` to accept an optional `due_date`. If not provided, it defaults to the current timestamp and a 'completed' status.
    - If a user says "I have a payment of 500 next Friday", the AI should flag this as `status='planned'`.

## 2. Intelligence Layer (`services/llm_helper.py`)
Teaching the AI to recognize future intent.

- **LLM Prompt Update:**
    - Update the system prompt to recognize temporal words (e.g., "next week", "in 10 days", "tomorrow").
    - Require the LLM to output a `planned=True` flag and a `due_date` in the JSON response if the user describes a future commitment.
- **NLP Refinement:**
    - Ensure "I paid" vs "I will pay" logic correctly routes to `completed` vs `planned`.

## 3. Forecast Engine (`services/database.py`)
Calculating the future.

- **New Aggregator:** `get_cash_flow_forecast()`
    - Retrieve all `completed` income/expenses for the last 30 days.
    - Retrieve all `planned` income/expenses for the *next* 30 days.
    - Combine these to generate a daily "Projected Balance" series.

## 4. Dashboard Visualization (`webapp/app.js` & `webapp/index.html`)
Wowing the user with a "Pulse" forecast.

- **Chart Upgrade:**
    - Modify the existing cash flow chart to show **Two zones**: **Solid Fill** for historical data and **Dashed/Faded Fill** for the projected forecast (Only for SMB accounts).
    - **Business KPIs:** Add "Runway" (How long cash lasts) and "Pending Payables" totals to the summary.
    - Add a "Upcoming List" component to the side panel showing the next 3 payments due.

## 5. Sheets ETL Integration (`services/sheets_etl.py`)
Keep the paper trail perfect.

- **Column Expansion:** 
    - Update `append_row` to include `Status` and `Due Date` columns.
    - Ensure the "Global Sync" correctly handles these new fields.

## 6. Proactive Notifications (New Module: `services/scheduler.py`)
Reminding the business owner.

- **Reminder Loop:**
    - Check the `planned` table daily.
    - If a payment is due within 24 hours, send a Telegram notification: "⚠️ Upcoming Payment: 500 for Rent due tomorrow."

---

## Step-by-Step Execution Plan

1.  **[ ] Onboarding Logic:** Add Account Type selection to the startup flow.
2.  **[ ] DB Migration:** Add `due_date`, `status`, and `account_type` to storage.
3.  **[ ] LLM Training:** Update prompts to handle "upcoming" intent and future dates.
4.  **[ ] ETL Update:** Update Google Sheets columns to match the new DB schema.
5.  **[ ] Forecast API:** Create the backend endpoint for projected cash flow.
6.  **[ ] Dashboard UI:** Implement the "Pulse" forecast chart on the web dashboard (Conditional).
7.  **[ ] Bot Interaction:** Add a "Pending Payments" button to the `/menu` (Only for SMB).
