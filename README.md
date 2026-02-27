# FinTechBot 🏦

FinTechBot is a premium, AI-powered Personal Wealth Manager and Financial Intelligence Engine built as a Telegram Bot. It allows users to log their cash flow, uncover behavioral spending patterns, and optimize their wealth over time using natural language. 

The bot is designed to be highly secure, robust, and production-ready for deployment as a microservice on serverless platforms like Google Cloud Run.

## 🌟 Key Features

- **Natural Language Expense Logging**: Simply tell the bot what you spent, e.g., *"Spent 150 shekels on an Uber"* or *"שילמתי 80 שקל על קפה"*. The bot uses Google's Gemini AI to automatically parse the amount, category, and description.
- **Auto-Categorization & Currency Conversion**: Automatically maps natural text to predefined categories (Food, Housing, Transport, etc.) and seamlessly converts foreign currencies (USD, EUR, GBP, etc.) to NIS using live exchange rates.
- **AI Financial Insights**: Generates personalized financial advice based on your configured Wealth Profile (age, income, goals) and spending patterns. **Now supports full language-matching**; insights will be generated in your preferred language.
- **Interactive Analytics Dashboard**: Access a rich, inline menu (`/menu`) within Telegram to view:
  - Last transactions with quick-undo and delete capabilities.
  - Monthly/yearly summaries and dynamic spend-breakdown pie charts.
  - Direct AI Insights button.
- **Redesigned Settings Hub**: A centralized, inline settings menu (`/settings`) to manage your profile (Language, Currency, Budget, Age, Income, Goals) one field at a time with instant feedback—no tedious multi-step interviews.
- **Performance Optimized**: Includes an in-process profile caching layer for ultra-fast translations and response times, even under high load.
- **Google Sheets Integration**: Automatically mirrors every transaction to a secure Google Sheet for external auditing and visualization.
- **Budgeting & Alerts**: Define a monthly budget and receive real-time alerts when you approach or exceed your target.
- **Single-Tenant Security**: Hardened against prompt-injection and locked to the authorized Telegram User ID.

## ⚙️ Project Mission (Phase 2) 🚀

We are currently expanding the bot into a **Comprehensive Wealth Command Center**. See [mission.md](mission.md) for details on:
- **Income Tracking**: Bidirectional cash flow monitoring (Revenue + Expenses).
- **Interactive Web Dashboard**: A widget-based web app serving deep analytics, predictive trends, and modular financial widgets.

## ⚙️ Architecture & Core Components

1. **Telegram User Interface (`bot.py`)**: 
   Uses `python-telegram-bot` to handle asynchronous interactions and inline keyboard callbacks. **Optimized for speed** with a thread-safe profile cache.
2. **AI Inference Engine (`llm_helper.py`)**: 
   Integrates with Gemini AI. Features a logic-driven pre-filter and secure JSON extraction patterns to prevent prompt injection.
3. **Database Layer (`database.py`)**: 
   A thread-safe SQLite database (`fintech.db`) handling all finance data, profile settings, and aggregations.
4. **FastAPI Microservice (`main.py`)**: 
   Serves webhooks and provides a secure REST API for the upcoming Web Dashboard. Fortified with API-Key security and rate limiting.
5. **ETL & Mirroring (`sheets_etl.py`)**: 
   Handles non-blocking background sync of data to External Cloud Storage (Google Sheets).
6. **Robust Testing Engine (`test_suite.py`)**:
   Contains over 140+ unit and integration tests to guarantee code Stability and AI accuracy.

## 🚀 Deployment

- **Google Cloud Run**: Fully configured for serverless deployment.
- **Docker**: Custom `Dockerfile` included for seamless containerized execution.
- **Continuous Integration**: Ready for Google Cloud Build with included `cloudbuild.yaml`.
