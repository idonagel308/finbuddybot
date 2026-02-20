import os
import logging
import hmac
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, validator
from typing import List, Optional
from starlette.status import HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS
import time
from collections import defaultdict

import database as db

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="FinTechBot API",
    docs_url=None,   # Disable Swagger UI in production
    redoc_url=None,   # Disable ReDoc in production
)

# --- Authentication ---
API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if not API_SECRET_KEY:
    logger.critical("API_SECRET_KEY not set! API will reject all requests.")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(api_key_header)):
    """Dependency that validates the API key on every request."""
    if not API_SECRET_KEY:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="API not configured"
        )
    if not api_key or not hmac.compare_digest(api_key, API_SECRET_KEY):
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
        )
    return api_key


# --- Rate Limiting ---
RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60  # seconds
_request_timestamps = defaultdict(list)


async def rate_limit_check(request: Request):
    """Simple IP-based rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old timestamps
    _request_timestamps[client_ip] = [
        ts for ts in _request_timestamps[client_ip] if now - ts < RATE_LIMIT_WINDOW
    ]

    # Periodic cleanup of stale IPs to prevent memory leak
    if len(_request_timestamps) > 1000:
        stale_ips = [
            ip for ip, ts_list in _request_timestamps.items()
            if not ts_list or (now - max(ts_list)) > 300
        ]
        for ip in stale_ips:
            del _request_timestamps[ip]

    if len(_request_timestamps[client_ip]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later."
        )

    _request_timestamps[client_ip].append(now)


# --- CORS Configuration ---
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)


# --- Pydantic Models with Validation ---
ALLOWED_CATEGORIES = {
    '🏠 Housing', '🍔 Food', '🚗 Transport', '🎉 Entertainment',
    '🛍️ Shopping', '❤️ Health', '📚 Education', '💸 Financial', '❓ Other'
}


class ExpenseModel(BaseModel):
    user_id: int
    amount: float
    category: str
    description: Optional[str] = ""

    @validator('amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        if v > 1_000_000:
            raise ValueError('Amount exceeds maximum allowed')
        return v

    @validator('category')
    def category_must_be_valid(cls, v):
        if v not in ALLOWED_CATEGORIES:
            raise ValueError(f'Invalid category. Must be one of: {", ".join(ALLOWED_CATEGORIES)}')
        return v

    @validator('description')
    def description_length_check(cls, v):
        if v and len(v) > 200:
            return v[:200]
        return v


class ExpenseResponse(BaseModel):
    id: int
    user_id: Optional[int]
    date: str
    amount: float
    category: str
    description: Optional[str]


# --- Routes ---

@app.get("/")
async def read_root():
    return {"status": "ok"}


@app.get("/expenses/{user_id}", response_model=List[ExpenseResponse],
         dependencies=[Depends(verify_api_key), Depends(rate_limit_check)])
async def get_expenses(user_id: int, limit: int = 20):
    """Get recent expenses for a user."""
    # Cap limit
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
            "description": row[4]
        })
    return expenses


@app.post("/expenses",
          dependencies=[Depends(verify_api_key), Depends(rate_limit_check)])
async def add_expense(expense: ExpenseModel):
    """Add a new expense."""
    try:
        db.add_expense(expense.user_id, expense.amount, expense.category, expense.description)
        return {"status": "success", "message": "Expense added"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid expense data")
    except Exception as e:
        logger.error(f"Error adding expense: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/summary/{user_id}",
         dependencies=[Depends(verify_api_key), Depends(rate_limit_check)])
async def get_summary(user_id: int):
    """Get total spent this month."""
    total = db.get_monthly_summary(user_id)
    return {"user_id": user_id, "monthly_total": total}


@app.get("/chart/{user_id}",
         dependencies=[Depends(verify_api_key), Depends(rate_limit_check)])
async def get_chart_data(user_id: int):
    """Get category totals for charts."""
    totals = db.get_category_totals(user_id)
    return totals


if __name__ == "__main__":
    import uvicorn

    # Initialize database
    db.init_db()

    # Bind to localhost only (not 0.0.0.0)
    uvicorn.run(app, host="127.0.0.1", port=8000)
