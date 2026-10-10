"""Bounded, thread-safe in-process token bucket middleware."""
from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("repo_analyzer_api")
ASK_PATH = re.compile(r"^/api/v1/analyses/[^/]+/ask$")


def rate_limit_rpm() -> int:
    raw = os.environ.get("RATE_LIMIT_RPM", "30")
    try:
        value = int(raw)
        if value < 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning("Invalid RATE_LIMIT_RPM; using default 30")
        return 30


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rpm: int | None = None, cap: int = 10000, ttl: float = 3600):
        super().__init__(app)
        self.rpm = rate_limit_rpm() if rpm is None else rpm
        self.cap = cap
        self.ttl = ttl
        self.buckets = OrderedDict()
        self.lock = threading.Lock()
        self.last_sweep_time = time.monotonic()
        self.request_counter = 0
        self.sweep_count = 0

    def _get_client_identity(self, request) -> str:
        trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "0").strip() in ("1", "true", "TRUE")
        if trust_proxy:
            xff = request.headers.get("x-forwarded-for", "")
            if xff and xff.strip():
                return xff.split(",")[0].strip()
        return request.client.host if (request.client and request.client.host) else "127.0.0.1"

    def _key(self, request) -> str:
        supplied_key = request.headers.get("x-api-key", "").strip()
        client_id = self._get_client_identity(request)
        if supplied_key:
            return hashlib.sha256(supplied_key.encode()).hexdigest() + ":" + client_id
        return client_id

    async def dispatch(self, request, call_next):
        path = request.url.path
        limited = request.method == "POST" and (path == "/api/v1/analyses" or bool(ASK_PATH.fullmatch(path)))
        if request.method == "OPTIONS" or not limited or self.rpm == 0:
            return await call_next(request)

        now = time.monotonic()
        key = self._key(request)

        with self.lock:
            self.request_counter += 1
            if now - self.last_sweep_time > 10.0 or self.request_counter >= 100:
                self.last_sweep_time = now
                self.request_counter = 0
                self.sweep_count += 1
                expired = [k for k, v in self.buckets.items() if now - v[1] > self.ttl]
                for k in expired:
                    del self.buckets[k]

            tokens, last = self.buckets.pop(key, (float(self.rpm), now))
            tokens = min(float(self.rpm), tokens + (now - last) * self.rpm / 60.0)

            if tokens < 1.0:
                self.buckets[key] = (tokens, now)
                retry = max(1, math.ceil((1.0 - tokens) / (self.rpm / 60.0)))
                return JSONResponse(
                    {"detail": f"Rate limit exceeded. Try again in {retry} seconds."},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )

            self.buckets[key] = (tokens - 1.0, now)
            while len(self.buckets) > self.cap:
                self.buckets.popitem(last=False)

        return await call_next(request)
