# FinTechBot: Phase 2 Mission 🚀

## Executive Summary
Convert FinTechBot from an expense-only tracker into a **Comprehensive Wealth Management Dashboard**. This next phase introduces bidirectional cash flow tracking (Income + Expenses) and a rich, interactive Web Application that acts as a customizable financial command center. 

This mission is split into two parallel tracks:
**Track A:** Telegram UI & Bot Logic Improvements (The Data Engine)
**Track B:** The Interactive Web Dashboard (The Command Center)

---

## 🟢 Track A: Bot & Data UI Improvements

The bot already possesses the database schema (`type = 'income'`) to store income, but the user interface actively ignores it. The goal of Track A is to elevate "Income" to be a first-class citizen alongside "Expenses."

### 1. NLP Income Recognition
- **Smart Parsing Modification:** Update `llm_helper.py` prompt engineering to differentiate between spending and receiving.
  - *Example 1:* "Got paid 5000 from client" ➡️ `type: income`, `amount: 5000`
  - *Example 2:* "Sold my old bike for 300" ➡️ `type: income`, `amount: 300`
- **Fallback Regex:** Enhance regex fallback to catch keywords like "earned", "got paid", "received", "salary".

### 2. Comprehensive Dashboard (Telegram UI)
- **Net Worth/Cash Flow View:** Modify the `/menu` dashboard to show:
  - Total Income: ₪X
  - Total Expenses: ₪Y
  - **Net Cash Flow:** ₪(X - Y)
- **Category Splitting:** If a user clicks the "Pie Chart" or "Monthly List", clearly separate money *in* vs money *out* so pie charts don't crash or skew combining the two. 

### 3. Smart Notifications
- **Goal Tracking:** Provide proactive Telegram notifications when a user adds an income that helps them hit one of their stated "Goals" from the Settings menu.

---

## 🔵 Track B: Web Application Dashboard

Telegram's UI is great for quick logging, but limited for deep data analysis. Track B will build a modern, responsive Web App (served by FastAPI) that users can open directly from the Telegram Bot via a Telegram Web App button.

### 1. Web App Architecture
- **Backend:** Expand the existing `/api/webapp/` endpoints in `main.py` to deliver robust data payloads (Net flow, historical data). Add security via Telegram's `initData` verification.
- **Frontend Stack:** HTML/JS/CSS (Vanilla + Modern CSS variables) or Next.js/Vite (if a complex reactive system is preferred). Using a dynamic, widget-based layout (Grid/Flexbox).
- **Aesthetics:** "Wow factor" UI. Glassmorphism, tailored dark/light mode scaling, smooth micro-animations, and premium typography (e.g., *Inter* or *Outfit* fonts). No generic templates.

### 2. The Widget Interface
The web app will be a modular canvas where users can toggle what matters to them:
- **Widget 1: The Pulse (Cash Flow)** 
  - Dynamic line charts showing Income vs Expenses over the month.
- **Widget 2: Category Donuts**
  - Interactive charts using Chart.js or Recharts to drill down into specific spending categories.
- **Widget 3: The Budgeting Space**
  - Visual progress bars for the overall monthly budget. (e.g. Green: Safe, Orange: Warning, Red: Exceeded).
- **Widget 4: AI Insights Panel**
  - A dedicated view for Gemini-generated insights running on the full dataset, summarizing behavioral trends.

### 3. Future Roadmap (Phase 2.5)
- **Predictive Analytics:** Once enough data is gathered, implement a "Future Forecast" widget that predicts end-of-month cash flow based on the user's historical daily spending velocity.
- **Custom Budgets:** Allow users to set budgets *per category* (e.g., ₪1500 for Food, ₪500 for Transport) via the Web UI, overriding the single global budget.

---

## 🛠️ Execution Plan (Next Steps)

1. **DB & Endpoint Readiness:** Audit `database.py` and `main.py` WebApp endpoints to ensure they accurately return income arrays separately from expense arrays. 
2. **LLM Prompt Update:** Modify the Gemini prompt instructions to properly extract and tag `transaction_type: 'income' | 'expense'`.
3. **Web Scaffold:** Initialize the frontend framework/files inside the project.
4. **Widget Build:** Implement the overarching dashboard grid and the first two widgets (Cash Flow & Categories). 
5. **Security Integration:** Secure the `/api/webapp/` endpoints ensuring only the authenticated Telegram user can view their data.
