"""Authentication middleware kept separate from application wiring."""
from __future__ import annotations

import hmac
import logging
import math
import os
import threading
import time
from collections import OrderedDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("repo_analyzer_api")


def auth_fail_rpm() -> int:
    raw = os.environ.get("AUTH_FAIL_RPM", "20")
    try:
        val = int(raw)
        if val < 0:
            raise ValueError
        return val
    except ValueError:
        logger.warning("Invalid AUTH_FAIL_RPM; using default 20")
        return 20


class APIKeyMiddleware(BaseHTTPMiddleware):
    _open_paths = {"/health", "/api/v1/health", "/docs", "/redoc", "/openapi.json"}

    def __init__(self, app, cap: int = 10000, ttl: float = 3600):
        super().__init__(app)
        self.cap = cap
        self.ttl = ttl
        self.fail_buckets = OrderedDict()
        self.lock = threading.Lock()
        self.last_sweep_time = time.monotonic()
        self.request_counter = 0

    def _get_client_ip(self, request) -> str:
        trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "0").strip() in ("1", "true", "TRUE")
        if trust_proxy:
            xff = request.headers.get("x-forwarded-for", "")
            if xff and xff.strip():
                return xff.split(",")[0].strip()
        return request.client.host if (request.client and request.client.host) else "127.0.0.1"

    async def dispatch(self, request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        expected = os.environ.get("API_KEY", "").strip()
        path = request.url.path
        public = (
            (request.method == "GET" and path in {"/health", "/api/v1/health"})
            or path in {"/docs", "/redoc", "/openapi.json"}
            or path.startswith(("/docs/", "/redoc/"))
        )
        if expected and not public:
            supplied = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                ip = self._get_client_ip(request)
                rpm = auth_fail_rpm()
                if rpm > 0:
                    now = time.monotonic()
                    with self.lock:
                        self.request_counter += 1
                        if now - self.last_sweep_time > 10.0 or self.request_counter >= 100:
                            self.last_sweep_time = now
                            self.request_counter = 0
                            expired = [k for k, v in self.fail_buckets.items() if now - v[1] > self.ttl]
                            for k in expired:
                                del self.fail_buckets[k]
                        tokens, last = self.fail_buckets.pop(ip, (float(rpm), now))
                        tokens = min(float(rpm), tokens + (now - last) * rpm / 60.0)
                        if tokens < 1.0:
                            self.fail_buckets[ip] = (tokens, now)
                            retry = max(1, math.ceil((1.0 - tokens) / (rpm / 60.0)))
                            return JSONResponse(
                                {"detail": "Authentication failure rate limit exceeded. Please try again later."},
                                status_code=429,
                                headers={"Retry-After": str(retry)},
                            )
                        self.fail_buckets[ip] = (tokens - 1.0, now)
                        while len(self.fail_buckets) > self.cap:
                            self.fail_buckets.popitem(last=False)
                return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
        return await call_next(request)
