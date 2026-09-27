"""
security.py — the public-internet hardening for the API.

The app goes online in Israel, where the Privacy Protection (Data Security)
Regulations 2017 require a system connected to the internet to be protected against
unauthorised access, and Amendment 13 (in force 2025-08-14) counts IP addresses as
personal data. This module holds the pieces that make the API safe to expose,
configured from the environment so local development keeps working unchanged:

  ALLOWED_ORIGINS    comma-separated extra CORS origins (the Railway frontend and
                     localhost are allowed by default, see `cors_kwargs`)
  NOTES_ADMIN_TOKEN  required to READ the analyst notes; without it they cannot be
                     read over HTTP at all (they were publicly listable)
  ENABLE_DOCS        '1' to expose /docs and /openapi.json (off by default in prod)
  RATE_LIMIT_PER_MIN per-IP request budget for the expensive endpoints (default 120)

No IP address is written to disk anywhere: the rate limiter keeps a short in-memory
window only, so the limiter itself creates no personal-data store.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# A ticker is 1-10 characters of letters, digits, dot, dash or caret (BRK.B, ^GSPC,
# BTC-USD). Anything else is refused before it reaches the data layer.
TICKER_RE = re.compile(r'^[A-Z0-9.\-^=]{1,10}$')

NOTE_MAX_CHARS = 2000
NOTE_MAX_PER_MIN = 5


def clean_ticker(raw: str) -> str:
    t = (raw or '').strip().upper()
    if not TICKER_RE.match(t):
        raise HTTPException(status_code=400, detail='invalid ticker')
    return t


def cors_kwargs() -> dict:
    """
    Browsers may call the API only from the app's own frontends: the local dev
    servers, any Railway-hosted frontend of this project, and whatever
    ALLOWED_ORIGINS adds (a custom domain). It used to be `*` — any website could
    drive the scanner from a visitor's browser.
    """
    extra = [o.strip() for o in os.environ.get('ALLOWED_ORIGINS', '').split(',') if o.strip()]
    local = [f'http://localhost:{p}' for p in (4200, 4201, 6000, 8123)] + \
            [f'http://127.0.0.1:{p}' for p in (4200, 4201, 6000, 8123)]
    return {
        'allow_origins': local + extra,
        'allow_origin_regex': r'https://[a-z0-9-]+\.up\.railway\.app',
        'allow_methods': ['GET', 'POST'],
        'allow_headers': ['Content-Type', 'X-Admin-Token'],
        'allow_credentials': False,
    }


SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=()',
    'Cross-Origin-Resource-Policy': 'cross-origin',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'Cache-Control': 'no-store',
}


async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


class RateLimiter:
    """
    A sliding one-minute window per client IP, in memory only (nothing persisted —
    an IP address is personal data under Amendment 13, so none is stored).
    """

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, request: Request, cost: int = 1, per_min: int | None = None,
              bucket: str = 'api') -> None:
        limit = per_min or self.per_min
        # separate budgets per endpoint group, so browsing stocks never uses up the
        # allowance for leaving a note and vice versa
        key = f'{bucket}:{client_ip(request)}'
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) + cost > limit:
                raise HTTPException(status_code=429, detail='too many requests — try again in a minute')
            for _ in range(cost):
                q.append(now)
            if len(self._hits) > 10000:          # bound memory under a spray of IPs
                for k in [k for k, v in self._hits.items() if not v][:5000]:
                    del self._hits[k]


def client_ip(request: Request) -> str:
    # Railway terminates TLS in front of the app and forwards the client address
    fwd = request.headers.get('x-forwarded-for', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.client.host if request.client else 'unknown'


limiter = RateLimiter(int(os.environ.get('RATE_LIMIT_PER_MIN', '120')))


def require_admin(request: Request) -> None:
    token = os.environ.get('NOTES_ADMIN_TOKEN', '')
    given = request.headers.get('x-admin-token', '')
    if not token or not given or not _consteq(token, given):
        raise HTTPException(status_code=403, detail='forbidden')


def _consteq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def docs_enabled() -> bool:
    return os.environ.get('ENABLE_DOCS', '') == '1'
