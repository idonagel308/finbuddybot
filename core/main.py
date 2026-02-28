"""
main.py — FinTechBot REST API (FastAPI).

Hardened API microservice with authentication, rate limiting,
input validation, and proper error handling.

Run:  python main.py
"""

import os
import time
import logging

from dotenv import load_dotenv
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List
from contextlib import asynccontextmanager
from telegram import Update
import asyncio

import services.database as db
from .bot_setup import get_application
from .models import ExpenseModel, ExpenseResponse
from .security import verify_api_key, rate_limit_check, verify_telegram_webapp

load_dotenv()

# ── Logging & Uptime ──
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_start_time = time.time()

# ── Lifespan & Bot ──
telegram_app = None  # initialized in background task after yield

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize DB synchronously (fast, local), then yield immediately
    # so Cloud Run healthchecks pass. The Telegram bot inits in the background.
    global telegram_app
    try:
        db.init_db()
        # Cold Start: Sync from Sheets to populate local SQLite cache
        db.sync_from_sheets()
    except Exception as e:
        logger.error(f"DB init/sync failed: {e}")

    async def _start_bot():
        global telegram_app
        try:
            telegram_app = get_application()
            await telegram_app.initialize()
            await telegram_app.start()
            logger.info("Telegram bot started successfully.")
        except Exception as e:
            logger.error(f"Bot startup failed: {e}")

    # Yield immediately so the web server binds port 8080, then start bot in background
    asyncio.create_task(_start_bot())
    yield

    # Shutdown
    if telegram_app:
        try:
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception as e:
            logger.warning(f"Error during shutdown: {e}")

app = FastAPI(
    title="FinTechBot API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan
)

# ── Web App Static Files ──
import os
from fastapi.responses import FileResponse
webapp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp")
if os.path.exists(webapp_dir):
    app.mount("/static", StaticFiles(directory=webapp_dir), name="static")
    
    @app.get("/webapp")
    async def serve_webapp():
        return FileResponse(os.path.join(webapp_dir, "index.html"))
else:
    logger.warning("Webapp directory not found, static files will not be served.")


# ── Global Exception Handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all: never leak stack traces to clients."""
    import traceback
    traceback.print_exc()
    logger.error(f"Unhandled API error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


# ── CORS ──
allowed_origins_str = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
)
allowed_origins = [
    origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# ── Validators ──

def _validate_user_id(user_id: int):
    """Ensure user_id is in a sane range."""
    if user_id < 0 or user_id > 10**15:
        raise HTTPException(status_code=400, detail="Invalid user_id")


# ── Routes ──

@app.get("/")
async def health_check():
    """Health check with uptime."""
    uptime = int(time.time() - _start_time)
    return {"status": "ok", "uptime_seconds": uptime, "engine": "webhook"}


@app.post("/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Ingest Telegram updates via Webhook."""
    import hmac
    expected_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not hmac.compare_digest(token, expected_token):
        logger.warning("Unauthorized webhook access attempt.")
        raise HTTPException(status_code=403, detail="Forbidden")
    
    try:
        data = await request.json()
        update = Update.de_json(data, telegram_app.bot)
        await telegram_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing telegram update: {e}")
        return JSONResponse(status_code=500, content={"detail": "Error processing update"})


@app.get(
    "/expenses/{user_id}",
    response_model=List[ExpenseResponse],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_expenses(user_id: int, limit: int = 20):
    """Get recent expenses for a user."""
    _validate_user_id(user_id)
    limit = min(max(1, limit), 50)

    rows = db.get_recent_expenses(user_id=user_id, limit=limit)

    expenses = []
    for row in rows:
        expenses.append({
            "id": row[0],
            "user_id": user_id,
            "date": row[1],
            "amount": row[2],
            "category": row[3],
            "description": row[4],
        })
    return expenses


# --- Pydantic Schema overriding models.py for Strict Validation ---
class InboundExpenseModel(BaseModel):
    user_id: int = Field(gt=0, lt=10**15)
    amount: float = Field(gt=0, le=db.MAX_AMOUNT)
    category: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=db.MAX_DESCRIPTION_LENGTH)

@app.post(
    "/expenses",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def add_expense(expense: InboundExpenseModel, background_tasks: BackgroundTasks):
    """Add a new expense."""
    try:
        db.add_expense(
            expense.user_id, expense.amount,
            expense.category, expense.description
        )
        
        return {"status": "success", "message": "Expense added"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error adding expense: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.delete(
    "/expenses/{user_id}/{expense_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def delete_expense(user_id: int, expense_id: int):
    """Delete a specific expense (owner-only)."""
    _validate_user_id(user_id)
    success = db.delete_expense(user_id, expense_id)
    if success:
        return {"status": "success", "message": "Expense deleted"}
    raise HTTPException(status_code=404, detail="Expense not found or not owned by user")


@app.get(
    "/summary/{user_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_summary(user_id: int):
    """Get total spent this month."""
    _validate_user_id(user_id)
    total, _ = db.get_monthly_summary(user_id)
    return {"user_id": user_id, "monthly_total": total}


@app.get(
    "/chart/{user_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_chart_data(user_id: int):
    """Get category totals for charts.
    
    Returns a flat {category: amount} dict (expense-only) suitable for
    pie charts and frontend bar charts. Uses get_expense_totals() so the
    response format is stable even if the internal DB schema changes.
    """
    _validate_user_id(user_id)
    totals = db.get_expense_totals(user_id)
    return totals


# ── Web App API (Phase 2: Live Backend Integration) ──
@app.get("/api/webapp/dashboard")
async def webapp_dashboard(
    user_id: int = Depends(verify_telegram_webapp),
    year: int = None,
    month: int = None
):
    """Serve real data for the Telegram Web App dashboard."""
    _validate_user_id(user_id)
    profile = db.get_profile(user_id) or {"currency": "NIS", "yearly_income": 0, "language": "English"}
    
    # 1. Budget and Monthly Spend
    total_spent, total_income = db.get_monthly_summary(user_id, year=year, month=month)
    monthly_budget = db.get_budget(user_id) or 0
    net_flow = total_income - total_spent
    
    # Calculate savings (simplistic tracking for now: income - spent. Real implementation would track specific 'transfer' txs)
    current_savings = max(0, net_flow) 

    budget_data = {
        "spent": total_spent,
        "total": monthly_budget,
        "savings": current_savings
    }

    # 1.5 Generate Real CashFlow Series for the line chart
    cashFlowSeries = db.get_daily_aggregation(user_id, year=year, month=month)

    # 2. Recent Transactions (Formatted for the JS list widget)
    # If a specific month is selected, we should fetch that month's expenses.
    if month is not None or year is not None:
        rows = db.get_monthly_expenses(user_id, year=year, month=month)[:10]
    else:
        rows = db.get_recent_expenses(user_id, limit=6)
        
    recent = []
    for r in rows:
        amount = r[2]
        cat = r[3]
        tx_type = 'inc' if cat in db.ALLOWED_CATEGORIES.intersection({'Salary', 'Investment', 'Gift'}) or r[5] == 'income' else 'exp'
        
        # Determine emoji icon based on simple mapping
        icon = '🚗' if cat == 'Transport' else '🍔' if cat == 'Food' else '💼' if tx_type == 'inc' else '💸'
        
        recent.append({
            "id": r[0],
            "title": r[4] or cat,
            "category": cat,
            "amount": amount,
            "type": tx_type,
            "time": r[1][:10], # Truncate ISO to YYYY-MM-DD
            "icon": icon
        })

    # 3. Dynamic Goal Data (Mocked persistence for Phase 2, usually stored in DB)
    goal_data = {
        "name": "New Goal",
        "target": 10000,
        "current": current_savings
    }
        
    # 4. Sync AI Insight from Bot
    # Use the requested year/month or the current one
    y = year or datetime.now().year
    m = month or datetime.now().month
    insight = db.get_insight(user_id, y, m)

    if not insight:
        insight = f"""
            <p><strong>💡 Note:</strong> No AI insights generated for this month yet.</p>
            <p>Tap <strong>AI Context Insights</strong> in the Telegram bot to generate a fresh analysis.</p>
        """

    return {
        "budget": budget_data,
        "netFlow": { "income": total_income, "expenses": total_spent },
        "cashFlowSeries": cashFlowSeries,
        "transactions": recent,
        "goal": goal_data,
        "insight": insight
    }

@app.get("/api/webapp/categories")
async def webapp_categories(
    user_id: int = Depends(verify_telegram_webapp),
    year: int = None,
    month: int = None
):
    """Serve category breakdown for the donut chart."""
    _validate_user_id(user_id)
    totals = db.get_expense_totals(user_id, year=year, month=month)
    
    # Filter out income categories for the expense breakdown donut
    expense_totals = {k: v for k, v in totals.items() if k not in {'Salary', 'Investment', 'Gift'}}
    return expense_totals or {"No Category": 0}

# ── Settings Persistence Endpoints ──

class UserSettings(BaseModel):
    theme: str = None
    layout: str = None
    budget_target: float = None
    financial_goal: str = None
    language: str = None
    accent_color: str = None

@app.get("/api/webapp/settings")
async def get_webapp_settings(user_id: int = Depends(verify_telegram_webapp)):
    """Fetch user-specific dashboard preferences."""
    settings = db.get_user_settings(user_id)
    return settings

@app.post("/api/webapp/settings")
async def save_webapp_settings(
    settings: UserSettings, 
    user_id: int = Depends(verify_telegram_webapp)
):
    """Save user-specific dashboard preferences."""
    db.save_user_settings(
        user_id,
        theme=settings.theme,
        layout=settings.layout,
        budget_target=settings.budget_target,
        financial_goal=settings.financial_goal,
        language=settings.language,
        accent_color=settings.accent_color
    )
    return {"status": "success"}

class WebAppTransaction(BaseModel):
    amount: float
    category: str
    description: str = ""

@app.post("/api/webapp/transaction")
async def webapp_transaction(
    tx: WebAppTransaction, 
    user_id: int = Depends(verify_telegram_webapp)
):
    """Log a transaction from Web App."""
    _validate_user_id(user_id)
    try:
        db.add_expense(user_id, tx.amount, tx.category, tx.description)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Webapp tx error: {e}")
        raise HTTPException(status_code=400, detail="Invalid data")


# ── Entry Point ──

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    
    # Use import string and reload=True to automatically apply code changes
    uvicorn.run("core.main:app", host="0.0.0.0", port=port, reload=True)

