# FinTechBot: Phase 3 Mission — The Secure Environment 🔐

## Executive Summary
Convert the interactive Web Dashboard from a prototype into a production-grade **Secure Financial Environment**. Phase 3 focuses on **Zero-Trust Architecture**, **SDK Stability**, and **Input Accuracy**: ensuring data privacy through Telegram's official HMAC authentication, restoring reliability via the legacy Gemini SDK, and perfecting natural language understanding for financial entries.

---

## 🎯 Core Objectives

### 1. Zero-Trust Authentication (The Vault)
Shift from manual JSON parameters to mandatory cryptographic validation for all API requests.
- **HMAC Signature Verification:** Implement the official Telegram `initData` handshake in `security.py`. Validate the `hash` using the `TELEGRAM_BOT_TOKEN`.
- **User Integrity:** No `user_id` should be accepted from the URL or Body if it doesn't match the ID embedded in the cryptographically signed `initData`.
- **Session Control:** Enforce a 24-hour expiration on all WebApp authentication signatures.

### 2. Deep Insights Synchronization
Bridge the gap between the Telegram Bot and the Web Dashboard.
- **Insight Persistence:** Store AI-generated behavioral analysis in the `insights` table (SQLite). 
- **WebApp Sync:** When a user opens the dashboard, it automatically fetches the latest analysis generated in the bot for that specific month/year.
- **Fallback Logic:** If no insight exists, provide a "Generate Insight" call-to-action that links back to the bot.

### 3. Permanent Personalization (Server-Side)
Move from browser-only `localStorage` to persistent database storage for a "seamless experience everywhere."
- **Settings Table:** Implement a `user_settings` table to store:
  - Dashboard Layout (Widget order and visibility).
  - Aesthetic Preferences (Selected theme and accent colors).
  - Custom Financial Goals & Budget targets.
- **Auto-Sync:** On login, the dashboard fetches these preferences to restore the user's customized command center instantly.

### 4. Advanced Historical Analysis
utilize the dashboard's "Time Period" controls for more than just aesthetics.
  - **Real-Time Pacing:** Replace mock "Pulse" data with real day-by-day cumulative spending for the selected month.
- **Year-Over-Year View:** Implement a "Years" view that compares the current year's net flow vs. previous years.

### 5. SDK Stability & Intelligence Audit
Ensure the bot understands the user and remains stable.
- **Legacy SDK Restoration:** Revert and lock the system to `google-generativeai` (legacy Gemini SDK) to prevent breaking changes from the new SDK.
- **Natural Language Audit:** Verify the bot correctly extracts amounts, categories, and types (income vs expense) from complex conversational inputs.
- **Error Handling:** Implement graceful fallbacks for LLM rate limits or connection failures.

---

## 🛠️ Execution Roadmap

### Step 1: Security Hardening
- [ ] Finalize `verify_telegram_webapp` in `security.py`.
- [ ] Remove all hardcoded `TEMP_USER_ID` or fallback logic in `main.py` and `app.js`.
- [ ] Update `test_suite.py` with an HMAC generator to simulate secure requests.

### Step 2: Persistence & Sync
- [ ] Create `user_settings` table in `database.py`.
- [ ] Implement `POST /api/webapp/settings` to save preferences from the Modal.
- [ ] Refactor `app.js` to load initial state from the API instead of `localStorage`.

### Step 3: Data Integrity
- [ ] Refactor "The Pulse" data aggregator to provide real daily expenditure sums.
- [ ] Perform a "Deep Audit" of the `expenses` table to ensure category mapping is 100% consistent between the Bot UI and Web UI.

### Step 4: Intelligence & Stability Restoration
- [ ] Revert and lock `google-generativeai` in `requirements.txt`.
- [ ] Audit `llm_helper.py` classification logic to ensure 95%+ accuracy.
- [ ] Run comprehensive input tests (English & Hebrew) to verify extraction reliability.

---

## ✅ Success Metrics
1. **User B cannot see User A's data**, even if they know their ID.
2. **Settings persist** if the user clears their browser cache.
3. **AI Insights** generated in the Telegram chat appear instantly on the Web Dashboard for the correct month.
4. **95%+ Input Accuracy** on complex, natural language transaction entries without system crashes.
5. **Legacy SDK Locked** and functional without `google-genai` conflicts.
