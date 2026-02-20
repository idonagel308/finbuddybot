"""
main.py — FinTechBot REST API (FastAPI).

This is the API microservice. It handles HTTP requests from:
- The React web frontend
- (Future) The Telegram bot via HTTP, when deployed separately

Run:  python main.py
Docs: Swagger/ReDoc disabled in production. Set docs_url="/docs" to re-enable.
"""

import os
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import List

import database as db
from models import ExpenseModel, ExpenseResponse
from security import verify_api_key, rate_limit_check

load_dotenv()

# ── Logging ──
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ──
app = FastAPI(
    title="FinTechBot API",
    docs_url=None,    # Disable in production; set to "/docs" for dev
    redoc_url=None,
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
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# ── Routes ──

@app.get("/")
async def read_root():
    return {"status": "ok"}


@app.get(
    "/expenses/{user_id}",
    response_model=List[ExpenseResponse],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_expenses(user_id: int, limit: int = 20):
    """Get recent expenses for a user."""
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


@app.post(
    "/expenses",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def add_expense(expense: ExpenseModel):
    """Add a new expense."""
    try:
        db.add_expense(
            expense.user_id, expense.amount,
            expense.category, expense.description
        )
        return {"status": "success", "message": "Expense added"}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid expense data")
    except Exception as e:
        logger.error(f"Error adding expense: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get(
    "/summary/{user_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_summary(user_id: int):
    """Get total spent this month."""
    total = db.get_monthly_summary(user_id)
    return {"user_id": user_id, "monthly_total": total}


@app.get(
    "/chart/{user_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_chart_data(user_id: int):
    """Get category totals for charts."""
    totals = db.get_category_totals(user_id)
    return totals


# ── Entry Point ──

if __name__ == "__main__":
    import uvicorn

    db.init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)
