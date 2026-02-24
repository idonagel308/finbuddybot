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
from typing import List

import database as db
import sheets_etl
from models import ExpenseModel, ExpenseResponse
from security import verify_api_key, rate_limit_check

load_dotenv()

# ── Logging ──
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ──
_start_time = time.time()

app = FastAPI(
    title="FinTechBot API",
    docs_url=None,    # Disabled in production; set to "/docs" for dev
    redoc_url=None,
)


# ── Global Exception Handler ──
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all: never leak stack traces to clients."""
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
    return {"status": "ok", "uptime_seconds": uptime}


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


@app.post(
    "/expenses",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def add_expense(expense: ExpenseModel, background_tasks: BackgroundTasks):
    """Add a new expense."""
    try:
        db.add_expense(
            expense.user_id, expense.amount,
            expense.category, expense.description
        )
        
        # Get the ID of the newly added expense
        expense_id = db.get_last_expense_id(expense.user_id)
        
        # Create dictionary for the ETL process
        expense_dict = {
            "id": expense_id,
            "user_id": expense.user_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "amount": expense.amount,
            "category": expense.category,
            "description": expense.description
        }
        
        # Enqueue the Google Sheets sync as a background task
        background_tasks.add_task(sheets_etl.append_expense_to_sheet, expense_dict)
        
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
    total = db.get_monthly_summary(user_id)
    return {"user_id": user_id, "monthly_total": total}


@app.get(
    "/chart/{user_id}",
    dependencies=[Depends(verify_api_key), Depends(rate_limit_check)],
)
async def get_chart_data(user_id: int):
    """Get category totals for charts."""
    _validate_user_id(user_id)
    totals = db.get_category_totals(user_id)
    return totals


# ── Entry Point ──

if __name__ == "__main__":
    import uvicorn

    db.init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)

