"""
models.py — Pydantic data models and category definitions.

This module is the single source of truth for:
- Allowed expense categories (clean strings, no emojis)
- Request/response schemas for the FastAPI endpoints
"""

from pydantic import BaseModel, validator
from typing import Optional


# ── Category Definitions ──
# Clean English strings only. The UI layer (bot, frontend) is responsible
# for mapping these to emoji-decorated display names.
ALLOWED_CATEGORIES = {
    'Housing',
    'Food',
    'Transport',
    'Entertainment',
    'Shopping',
    'Health',
    'Education',
    'Financial',
    'Other',
    'Salary',
    'Investment',
    'Gift',
}

MAX_AMOUNT = 1_000_000


# ── Request Models ──

class ExpenseModel(BaseModel):
    """Schema for creating a new expense via the API."""
    user_id: int
    amount: float
    category: str
    description: Optional[str] = ""

    @validator('amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Amount must be positive')
        if v > MAX_AMOUNT:
            raise ValueError('Amount exceeds maximum allowed')
        return v

    @validator('category')
    def category_must_be_valid(cls, v):
        if v not in ALLOWED_CATEGORIES:
            raise ValueError(
                f'Invalid category. Must be one of: {", ".join(sorted(ALLOWED_CATEGORIES))}'
            )
        return v

    @validator('description')
    def description_length_check(cls, v):
        if v and len(v) > 200:
            return v[:200]
        return v


# ── Response Models ──

class ExpenseResponse(BaseModel):
    """Schema for returning an expense from the API."""
    id: int
    user_id: Optional[int]
    date: str
    amount: float
    category: str
    description: Optional[str]
