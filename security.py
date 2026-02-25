"""
security.py — Authentication and rate limiting middleware.

Provides FastAPI dependencies for:
- API key validation via X-API-Key header (constant-time comparison)
- IP-based rate limiting with automatic stale-entry cleanup
"""

import os
import hmac
import time
import logging
from collections import defaultdict

from dotenv import load_dotenv
from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS

load_dotenv()

logger = logging.getLogger(__name__)


# ── API Key Authentication ──

API_SECRET_KEY = os.getenv("API_SECRET_KEY")
if not API_SECRET_KEY:
    logger.critical("API_SECRET_KEY not set! API will reject all requests.")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Depends(_api_key_header)):
    """
    FastAPI dependency — validates the X-API-Key header on every request.
    Uses hmac.compare_digest for constant-time comparison (timing-attack safe).
    """
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


# ── Rate Limiting ──

RATE_LIMIT_REQUESTS = 60
RATE_LIMIT_WINDOW = 60  # seconds
_request_timestamps: dict[str, list[float]] = defaultdict(list)


async def rate_limit_check(request: Request):
    """
    FastAPI dependency — simple IP-based rate limiting.
    Allows RATE_LIMIT_REQUESTS per RATE_LIMIT_WINDOW seconds per IP.
    Includes periodic cleanup to prevent memory leaks.
    """
    # Extract Real IP to prevent proxy starvation if deployed behind a Load Balancer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.headers.get("x-real-ip", request.client.host if request.client else "unknown")

    now = time.time()

    # Clean old timestamps for this IP
    _request_timestamps[client_ip] = [
        ts for ts in _request_timestamps[client_ip]
        if now - ts < RATE_LIMIT_WINDOW
    ]

    # Periodic cleanup of stale IPs (when map grows too large)
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
