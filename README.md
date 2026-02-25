# FinTechBot 🏦

FinTechBot is a premium, AI-powered Personal Wealth Manager and Financial Intelligence Engine built as a Telegram Bot. It allows users to log their cash flow, uncover behavioral spending patterns, and optimize their wealth over time using natural language. 

The bot is designed to be highly secure, robust, and production-ready for deployment as a microservice on serverless platforms like Google Cloud Run.

## 🌟 Key Features

- **Natural Language Expense Logging**: Simply tell the bot what you spent, e.g., *"Spent 150 shekels on an Uber"* or *"שילמתי 80 שקל על קפה"*. The bot uses Google's Gemini AI to automatically parse the amount, category, and description.
- **Auto-Categorization & Currency Conversion**: Automatically maps natural text to predefined categories (Food, Housing, Transport, etc.) and seamlessly converts foreign currencies (USD, EUR, GBP, etc.) to NIS using live exchange rates.
- **AI Financial Insights**: Generates personalized, world-class financial advice based on your configured Wealth Profile (age, income, goals) and your recent spending patterns.
- **Interactive Analytics Dashboard**: Access a rich, inline menu (`/menu`) within Telegram to view:
  - Last expenses and monthly/yearly summaries.
  - Beautiful, dynamic donut pie charts of your spending visually generated on the fly.
  - Dedicated AI insights.
- **Budgeting & Alerts**: Define a monthly budget (`/budget 5000`) and receive real-time alerts when you approach or exceed your target.
- **Single-Tenant & Hardened Security**: Locks the bot to only answer to your specific Telegram User ID. The system is hardened against prompt-injection attacks and includes robust input validation.

## ⚙️ Architecture & Core Components

The project is built using a modern, secure, and robust Python stack:

1. **Telegram User Interface (`bot.py`)**: 
   Uses `python-telegram-bot` to handle asynchronous user interactions, inline keyboard callbacks, and command routing. It leverages `ConversationHandler` for smooth onboarding flows and is configured to receive events via webhook.
2. **AI Inference Engine (`llm_helper.py`)**: 
   Integrates with the `google.generativeai` SDK. It has a pre-filter system to quickly detect expenses and uses Gemini to securely extract JSON data, actively protecting against prompt injection attacks.
3. **Database Layer (`database.py`)**: 
   A lightweight, thread-safe SQLite database (`fintech.db`). It handles all CRUD operations for expenses, calculates aggregations, and stores the user's Wealth Profile and Budget limits securely.
4. **FastAPI Microservice (`main.py`)**: 
   A hardened REST API built with `FastAPI`. It serves the `/webhook` endpoint for live Telegram updates and is fortified with strict API-Key security, CORS configurations, and IP-based rate limiting (`security.py`).
5. **Live Currency & Logic (`currency.py`, `models.py`)**: 
   `currency.py` fetches live exchange rates from APIs and parses symbols. `models.py` uses `pydantic` to enforce strict data validation schemas across the app.
6. **Robust Testing Engine (`test_suite.py`)**:
   A comprehensive test suite of over 140 passing unit and integration tests to guarantee the AI doesn't hallucinate data, prompt injections fail, and the core routing and database operations remain stable.

## 🚀 Deployment

FinTechBot is optimized for containerized production environments:
- **Google Cloud Run**: Fully supported and configured for deployment as a serverless container. Listens securely for Telegram webhooks.
- **Docker**: Includes a custom `Dockerfile` allowing for seamless containerized building and execution without local installation overhead.
