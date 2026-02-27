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
import json
import urllib.parse
from collections import defaultdict

from dotenv import load_dotenv
from fastapi import HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not set! WebApp auth will fail.")


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


# ── Telegram WebApp Authentication (initData Validation) ──

def validate_init_data(init_data: str) -> int:
    """
    Core validation logic for Telegram initData.
    Returns the user_id if valid, raises HTTPException otherwise.
    """
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        raise HTTPException(status_code=500, detail="Server configuration error")

    try:
        import hashlib
        
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if 'hash' not in parsed_data:
            raise HTTPException(status_code=401, detail="Invalid initData format")

        received_hash = parsed_data.pop('hash')
        data_check_list = sorted([f"{k}={v}" for k, v in parsed_data.items()])
        data_check_string = "\n".join(data_check_list)

        # 1. Create secret key
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        
        # 2. Generate expected hash
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if received_hash != expected_hash:
            logger.warning("Telegram WebApp hash mismatch!")
            raise HTTPException(status_code=401, detail="Authentication failed: hash mismatch")

        # 3. Check data age (24h)
        auth_date = int(parsed_data.get('auth_date', 0))
        if time.time() - auth_date > 86400:
            raise HTTPException(status_code=401, detail="Session expired")

        # 4. Extract user_id
        user_json = parsed_data.get('user')
        if not user_json:
            raise HTTPException(status_code=401, detail="User data missing")
        
        user_data = json.loads(user_json)
        return int(user_data['id'])
        
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        logger.error(f"WebApp Auth Error: {e}")
        raise HTTPException(status_code=401, detail="Corrupt authentication data")

async def verify_telegram_webapp(request: Request):
    """
    FastAPI dependency — validates the Telegram WebApp initData 
    provided in the Authorization header.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("WebAppData "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    init_data = auth_header.split(" ", 1)[1]
    return validate_init_data(init_data)
