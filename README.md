# FinTechBot 🏦

> **AI-Powered Personal Wealth Manager** — A production-grade Telegram bot with a full-stack Web Dashboard, powered by Google Gemini AI and backed by Google Cloud Firestore.

---

## ✨ What It Does

FinTechBot lives in your Telegram DMs and acts as your real-time financial copilot. Simply type a message describing a transaction — the AI parses it, categorizes it, and logs it instantly. A beautiful Web Dashboard provides a complete picture of your finances at a glance.

---

## 🌟 Core Features

### 💬 Natural Language Expense Logging
Type anything:
- *"Spent 150 on an Uber"*
- *"pizza and beer for 80 bucks"*
- *"קניתי נעליים ב350 שקל"* (Hebrew)
- *"Got paid 8000 salary"*

Gemini AI extracts the amount, category, currency, and description automatically. If the AI is unavailable, a regex fallback engine ensures the bot **never stops working** (graceful degradation).

### 🌐 Interactive Web Dashboard
Opens directly inside Telegram as a WebApp:
- **The Pulse** — real-time daily cash flow line chart
- **Monthly Control** — budget bar with spend tracking
- **Goal Tracker** — circular progress ring for a financial goal
- **Expense Breakdown** — animated donut category chart
- **Recent Activity** — scrollable transaction feed
- **AI Wealth Insight** — contextual behavioral analysis from Gemini
- Drag-and-drop widget layout, dark/light mode, language toggle (LTR/RTL)

### 🤖 Bot Commands
| Command | Description |
|---------|-------------|
| `/start` | First-time onboarding (language → currency → account type → budget) |
| `/menu` | Open the main inline dashboard |
| `/dashboard` | Launch the Web App directly |
| `/budget [amount]` | View or set monthly budget |
| `/undo` | Delete the last logged expense |
| `/export` | Download all expenses as a CSV file |
| `/settings` | Edit profile, language, currency, goals, account type |
| `/deleteall` | Wipe all expenses (with confirmation) |
| `/restart` | ⚠️ Full account reset — shows warning, clears all data on confirm |
| `/help` | Usage information |

### ⚙️ Settings Panel
All changeable via inline keyboards:
- 🌐 Language (English, Hebrew, Spanish, French, German, Russian, Arabic, Portuguese)
- 💱 Currency (NIS, USD, EUR, GBP, CAD, AUD, JPY or custom)
- 💰 Monthly budget
- 👤 Age & Annual income (used by AI context engine)
- 🎯 Financial goals (free text, fed into AI insights)
- 💼 Account Mode: **Personal** ↔ **Business** (toggle — unlocks Cash Flow Forecast)

### 🏢 Business Mode
Activates additional features for freelancers and SMBs:
- **Pending & Planned Payments** — track future expenses and bills
- **Cash Flow Forecast** — projected cash flow chart on the Web Dashboard
- **Pending Payables** metric on the dashboard

### 🔔 Smart Notifications
- Proactive payment reminders via a background scheduler

---

## 🏗️ Architecture

```
FinTechBot/
├── core/
│   ├── main.py          # FastAPI app, webhook endpoint, all API routes
│   ├── bot_setup.py     # Telegram Application builder & handler registration
│   ├── config.py        # Global env config, logging, VALID_CALLBACKS whitelist
│   ├── security.py      # HMAC-SHA256 Telegram WebApp auth, API-key guard, rate limiting
│   └── models.py        # Pydantic request/response models
│
├── database/            # Google Cloud Firestore data layer
│   ├── __init__.py      # Async Firestore client initialization
│   ├── user_management.py    # Profile, budget, settings CRUD + reset_user_data()
│   ├── expense_operations.py # Add, delete, get expenses
│   ├── queries.py            # Monthly summaries, recent expenses, pending payments
│   ├── analytics_engine.py  # Aggregations, category totals, CSV export, AI insight persistence
│   └── exceptions.py        # Custom ExpenseError / ProfileError exceptions
│
├── services/            # Business logic
│   ├── llm_helper.py    # Gemini AI parsing (multi-model fallback) + regex fallback
│   ├── currency.py      # Live exchange rates with fallback cache
│   ├── charts.py        # Matplotlib pie chart generation for Telegram
│   ├── localization.py  # Multi-language string support
│   └── scheduler.py     # Background payment reminder job
│
├── handlers/            # Telegram UI & routing
│   ├── commands.py      # All slash command handlers
│   ├── messages.py      # NLP message handler with graceful AI error recovery
│   ├── callbacks.py     # Inline button callback router
│   ├── settings_ui.py   # Settings hub keyboard builder & input processing
│   ├── onboarding.py    # New user step-by-step setup flow
│   └── utils.py         # Shared decorators, safe-send, profile cache
│
├── webapp/              # Web Dashboard (served by FastAPI)
│   ├── index.html       # Glassmorphic SPA shell
│   ├── app.js           # Live data fetching, charts, interactions
│   └── style.css        # Full design system (dark/light themes, animations)
│
├── Dockerfile           # Optimized multi-stage Cloud Run image
├── cloudbuild.yaml      # CI/CD pipeline for Google Cloud Build
├── requirements.txt     # All Python dependencies
└── test_suite.py        # 92-test comprehensive validation suite
```

---

## 🔐 Security

- **Telegram Webhook Auth**: Token validated via constant-time HMAC comparison on every request
- **WebApp Data Auth**: `initData` HMAC-SHA256 verified on every API call from the dashboard
- **API Key Guard**: `X-API-Key` header required on administrative endpoints
- **Rate Limiting**: Per-user request throttling to prevent abuse
- **Input Sanitization**: Prompt injection patterns stripped from all user text before AI processing
- **Callback Whitelist**: All Telegram callback data validated against `VALID_CALLBACKS` set

---

## ☁️ Deployment (Google Cloud Run)

### Prerequisites
- A Google Cloud Project with Firestore in Native mode (`findb` database)
- A Cloud Run service (`fintech-bot`)
- Service account with `roles/datastore.user`

### Environment Variables
```env
TELEGRAM_BOT_TOKEN=      # Your bot token from @BotFather
GOOGLE_API_KEY=          # Gemini API key (ai.google.dev)
WEBAPP_URL=              # Your Cloud Run URL + /webapp
WEBHOOK_URL=             # Your Cloud Run base URL (optional, auto-detected)
GOOGLE_CLOUD_PROJECT=    # GCP project ID
FIRESTORE_DATABASE=      # Firestore database name (e.g. "findb")
ALLOWED_USERS=           # Comma-separated Telegram user IDs
API_SECRET_KEY=          # Secret for API-key authenticated endpoints
```

### Deploy
```bash
# Build and push via Cloud Build (CI)
gcloud builds submit --config cloudbuild.yaml

# Or directly via gcloud
gcloud run deploy fintech-bot --source . --region us-central1
```

---

## 💻 Local Development

```bash
# 1. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file (copy from .env.example)
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, GOOGLE_API_KEY, etc.

# 4. Run locally (polling mode)
python -m core.bot_setup

# 5. Or run the full FastAPI server (webhook mode)
python -m core.main
```

---

## 🧪 Testing

```bash
python test_suite.py
```

The test suite covers 92 test cases including:
- Intent detection (English + Hebrew)
- Input sanitization & prompt injection
- Expense data validation
- Category mapping & fuzzy matching
- LLM JSON extraction (live)
- Regex fallback parsing
- **Graceful degradation** (simulated AI outage)
- Message safety & Markdown escaping
- HMAC-SHA256 WebApp authentication
- Security module integrity

---

## 🔄 Recent Major Updates

| Update | Description |
|--------|-------------|
| **Firestore Migration** | Replaced SQLite with Google Cloud Firestore for scalable, async cloud-native data persistence |
| **google-genai SDK** | Upgraded from deprecated `google.generativeai` to the new `google-genai` SDK with multi-model fallback |
| **Graceful AI Degradation** | Bot never crashes on AI failures — regex fallback extracts expenses with zero downtime |
| **Onboarding Flow** | Step-by-step new user setup: Language → Currency → Account Type → Budget |
| **Business Mode** | Dedicated account type with Cash Flow Forecast and Pending Payments tracker |
| **Restart with Data Clear** | `/restart` now shows a warning and wipes all user data on confirm |
| **Settings Toggle Fixed** | Account type toggle in settings now correctly switches Personal ↔ Business |
| **Dashboard Empty State** | Web Dashboard no longer shows placeholder demo data for new users |
| **Webhook Race Fix** | Startup race condition resolved — bot safely returns 503 if not yet initialized |

---

*Built with Python 3.11 · FastAPI · python-telegram-bot · Google Gemini · Google Cloud Firestore · Google Cloud Run*
