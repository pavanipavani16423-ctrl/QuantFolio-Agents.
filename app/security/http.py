"""HTTP hardening: body size limit, security headers, per-address rate limits."""

import hmac
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class HardeningMiddleware:
    """Pure ASGI (keeps Server-Sent Events streaming untouched)."""

    def __init__(self, app, max_body_bytes: int) -> None:  # noqa: ANN001
        self.app = app
        self.max_body_bytes = max_body_bytes
        self._headers = [(k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_body_bytes:
            await JSONResponse({"detail": "request body too large"}, status_code=413)(scope, receive, send)
            return
        if b"chunked" in headers.get(b"transfer-encoding", b"").lower() and not length:
            # a chunked body has no declared size, so the limit could not be enforced
            await JSONResponse({"detail": "send Content-Length"}, status_code=411)(scope, receive, send)
            return

        async def send_with_headers(message) -> None:  # noqa: ANN001
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [h for h in self._headers if h[0] not in present]
            await send(message)

        await self.app(scope, receive, send_with_headers)


class A2AAuthMiddleware:
    """The A2A JSON-RPC endpoints (/a2a/*/rpc) need the same API key as /api/v1 and share a
    rate limit; Agent Cards stay public (discovery)."""

    def __init__(self, app, api_key: str | None, limiter: "RateLimiter") -> None:  # noqa: ANN001
        self.app = app
        self.api_key = api_key
        self.limiter = limiter

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path.startswith("/a2a/") and not path.endswith("agent-card.json"):
            headers = dict(scope.get("headers") or [])
            if self.api_key and not hmac.compare_digest(headers.get(b"x-api-key", b"").decode(), self.api_key):
                await JSONResponse({"detail": "invalid or missing API key"}, status_code=401)(scope, receive, send)
                return
            client = scope.get("client") or ("unknown", 0)
            try:
                self.limiter.check(f"a2a:{client[0]}")
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=429)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class RateLimiter:
    """Sliding window per client address (in memory; one API process)."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry = int(self.window - (now - hits[0])) + 1
            raise HTTPException(status_code=429, detail=f"too many requests; try again in {retry} s",
                                headers={"Retry-After": str(retry)})
        hits.append(now)


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"
