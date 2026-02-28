# FinTechBot: Phase 4 Mission — Persistence Integrity & Seamless UX �

## Executive Summary
Phase 4 addresses critical gaps in data longevity and user experience. Currently, the system suffers from "amnesia" regarding user profiles and settings upon restart, and the Telegram bot menu has navigational dead-ends. This phase will implement **Multi-Entity Cloud Sync** (recovering not just expenses, but also profiles and settings from Google Sheets) and a **Unified Navigation System** for the bot.

---

## 🎯 Core Objectives

### 1. Unified Cloud-Local Persistence (Anti-Amnesia)
Ensure that *every* user-specific data point survives a server restart or container wipe.
- **Entity Expansion:** Extend `sheets_etl.py` and `database.py` to synchronize three core entities:
    - **Expenses:** (Existing) Historical transaction data.
    - **Profiles:** User age, income, currency, and language preferences.
    - **Settings:** Web dashboard layout, theme, and financial goals.
- **Cold-Start Recovery 2.0:** On startup, the system must detect missing data in all three tables and pull the latest "truth" from the corresponding Google Sheets worksheets.
- **Reliability:** Implement mandatory `sync_from_sheets` inside the FastAPI `lifespan` event to ensure the bot is never "blind" to old data on boot.

### 2. High-Fidelity Navigation (The Loop)
Eliminate navigational friction in the Telegram Bot by ensuring every action has a clear path back to the dashboard.
- **Menu Accessibility:** 
    - Add a "🌐 Web Dashboard" button to the `settings_tools` menu.
    - Ensure the "Back to Menu" button is present on *all* secondary views (Last Transactions, Category Charts, AI Insights).
- **Persistent Header:** Ensure that after specific actions (like `/undo`), the bot re-presents the Main Menu to keep the user in the flow.

### 3. Profile Integrity Audit
Perfect the capture and storage of user attributes.
- **Auto-Sync on Update:** Any change to user profile (age, income) must trigger an immediate background sync to the "Profiles" worksheet in Google Sheets.
- **Validation:** Enforce strict type checking to prevent corrupted state from breaking the AI engine.

---

## 🛠️ Execution Roadmap

### Step 1: Multi-Sheet Support
- [ ] Update `sheets_etl.py` to handle multiple worksheets: `Expenses`, `Profiles`, and `Settings`.
- [ ] Implement `fetch_all_profiles()` and `fetch_all_settings()` in `sheets_etl.py`.
- [ ] Implement `rewrite_profiles()` and `rewrite_settings()` for wholesale cloud updates.

### Step 2: Persistence Overhaul
- [ ] Refactor `database.py`'s `sync_from_sheets()` to iterate through all entities and restore them to SQLite.
- [ ] Move the `sync_from_sheets()` trigger from `main.py`'s `if __name__ == "__main__"` to the `lifespan` startup event.
- [ ] Ensure `set_profile` and `save_user_settings` trigger a Sheets sync.

### Step 3: UX & Navigation
- [ ] Add `[InlineKeyboardButton("⬅️ Back to Menu", callback_data='main_menu')]` to all relevant keyboard responses in `callbacks.py`.
- [ ] Update `handlers/settings_ui.py` to include a "🌐 Open Dashboard" button.
- [ ] Implement a `main_menu` callback handler to return to the root dashboard from any state.

---

## ✅ Success Metrics
1. **Zero Data Loss:** After a full server restart, `/menu` correctly displays the user's previously set age, income, AND historical expenses.
2. **Infinite Loop:** A user can navigate from Menu -> Chart -> Menu -> Settings -> Dashboard without typing a single slash command.
3. **Cloud Mirror:** The Google Sheet contains three worksheets (`Expenses`, `Profiles`, `Settings`) that perfectly reflect the local SQLite state.
4. **Fast Startup:** The `lifespan` sync doesn't block API healthchecks but ensures data is ready before the first user response.
