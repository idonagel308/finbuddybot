# FinTechBot 🏦

FinTechBot is a premium, AI-powered Personal Wealth Manager and Financial Intelligence Engine. It's built as a professional, modular Python application featuring a Telegram Bot interface and an integrated Web Dashboard.

## 🌟 Key Features

- **Natural Language Expense Logging**: Gemini AI automatically parses amount, category, and description from messages like *"Spent 150 on an Uber"* or Hebrew equivalents.
- **Interactive Web Dashboard**:
  - **The Pulse**: Real-time cumulative daily cashflow charts.
  - **Dynamic Insights**: AI-generated financial behavioral analysis.
  - **Customization**: Drag-and-drop widget layout, dark/light modes, and multi-language support.
- **Production-Grade Security**: HMAC-SHA256 official Telegram authentication, API-key protection, and rate limiting.
- **Enterprise-ReadyTo ensure everything runs smoothly, rely on the detailed `.env` templates provided and review the logging outputs carefully.

<!-- Updated for CI trigger -->- **Modular Architecture**: Clean separation of concerns for simplified maintenance and scaling.

## 📂 Project Structure

The project has been refactored from a monolith into a professional directory structure:

### 1. `core/` (Foundation)
- `core/main.py`: FastAPI application entry point and WebApp routes.
- `core/bot_setup.py`: Bot initialization and handler registration.
- `core/security.py`: Cryptographic validation (HMAC) and rate limiting.
- `core/config.py`: Centralized environment configuration and logging.
- `core/models.py`: Pydantic data models for the API.

### 2. `services/` (Business Logic)
- `services/database.py`: Optimized SQLite data layer with daily backups.
- `services/llm_helper.py`: AI parsing and insight generation (Gemini AI).
- `services/sheets_etl.py`: Non-blocking Google Sheets synchronization.
- `services/currency.py`: Currency conversion logic with live fallbacks.
- `services/charts.py`: Automated chart generation for Telegram.

### 3. `handlers/` (UI & Routing)
- `handlers/commands.py`: Telegram command logic (`/start`, `/menu`, etc.).
- `handlers/messages.py`: Natural language processing and transaction routing.
- `handlers/callbacks.py`: Interactive inline keyboard logic.
- `handlers/settings_ui.py`: User profile management and settings navigation.
- `handlers/utils.py`: Shared Telegram-specific helpers and decorators.

### 4. `webapp/` (Frontend)
- `webapp/index.html`: Modern, glassmorphic dashboard interface.
- `webapp/app.js`: Highly interactive SPA logic with fallback offline states.

## 🚀 Getting Started

### Local Setup
1. **Clone & Install**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure**: Create a `.env` file with your `TELEGRAM_BOT_TOKEN`, `GOOGLE_API_KEY`, and `WEBAPP_URL`.
3. **Run**:
   ```bash
   python main.py
   ```

### Deployment
- **Docker**: The included `Dockerfile` is optimized for Google Cloud Run.
- **CI/CD**: `cloudbuild.yaml` is provided for automated GCP deployments.

---
*Verified with a comprehensive suite of 162+ unit and intelligence tests.*
