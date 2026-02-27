# FinTechBot 🏦

FinTechBot is a premium, AI-powered Personal Wealth Manager and Financial Intelligence Engine built as a Telegram Bot and integrated Web Dashboard. It allows users to log their cash flow, uncover behavioral spending patterns, and optimize their wealth over time using natural language. 

The bot is designed for production-level security, featuring cryptographic session validation and a robust microservice architecture.

## 🌟 Key Features

- **Natural Language Expense Logging**: Simply tell the bot what you spent, e.g., *"Spent 150 shekels on an Uber"* or *"שילמתי 80 שקל על קפה"*. Gemini AI automatically parses amount, category, and description.
- **Enhanced Web Dashboard**: A high-performance, responsive web app featuring:
  - **The Pulse**: A cumulative daily cashflow and spending line chart.
  - **Dynamic Insights**: AI-generated financial context synced instantly from your bot.
  - **Real-Time Pacing**: Budget progress bars and net flow tracking.
- **AI Insight Synchronization**: Insights generated via the Telegram Bot are stored centrally and shared with the Web Dashboard, ensuring a unified financial context across all devices.
- **Auto-Categorization & Currency Conversion**: Maps natural text to predefined categories and converts foreign currencies (USD, EUR, GBP, etc.) to NIS using live exchange rates.
- **Redesigned Settings Hub**: A centralized, inline settings menu (`/settings`) to manage your profile (Language, Currency, Budget, Age, Income, Goals) with instant persistence.
- **Security-First Architecture**: 
  - **HMAC-SHA256 Auth**: Official Telegram WebApp signature verification for secure dashboard access.
  - **API-Key Hardening**: REST API secured with constant-time comparison and rate limiting.
  - **ID-Isolation**: Multi-tenant data separation locked to the authorized Telegram User ID.
- **Google Sheets Integration**: Automatically mirrors every transaction to a secure Google Sheet for external auditing.

## ⚙️ Project Evolution (Phase 3 Complete) ✅

We have successfully transitioned from a simple bot to a **Full-Stack Financial Ecosystem**. 
- **Bidirectional Tracking**: Full support for both Revenue and Expenses.
- **Permanent Personalization**: User settings (theme, budget, language) persist across sessions and platforms.
- **Real-Time Sync**: Zero-latency data flow between Telegram, SQLite, and the Web UI.

## ⚙️ Architecture & Core Components

1. **Telegram Interface (`bot.py`)**: Handles asynchronous user interaction and inline callback routing.
2. **AI Inference Engine (`llm_helper.py`)**: Integrates Gemini AI with secure pre-filtering and JSON-slicing logic.
3. **Database Layer (`database.py`)**: SQLite (`fintech.db`) with optimized daily aggregation and user-preference persistence.
4. **FastAPI Microservice (`main.py`)**: Secured REST API serving encrypted data to the Web Dashboard.
5. **Security Module (`security.py`)**: Implements official Telegram WebAppData validation and IP-based rate limiting.
6. **Robust Testing Engine (`test_suite.py`)**:
   Contains **162+ unit and integration tests** guaranteeing cryptographic security and parsing accuracy.

## 🚀 Deployment

- **Google Cloud Run**: Fully configured for serverless deployment.
- **Docker**: Custom `Dockerfile` included with hardened `.dockerignore` policies.
- **Continuous Integration**: Ready for Google Cloud Build with included `cloudbuild.yaml`.

---
*FinTechBot is verified with 162/162 successful tests.*
