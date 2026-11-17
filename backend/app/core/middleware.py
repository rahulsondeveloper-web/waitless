"""Request id + access log middleware (pure ASGI so it also wraps streaming responses)."""

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

log = logging.getLogger("waitless.access")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode()[:64]
        request_id = incoming or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            seconds = time.perf_counter() - started
            METRICS.observe(scope["method"], status_code, seconds)
            log.info("%s %s -> %s (%.1f ms)", scope["method"], scope["path"], status_code, seconds * 1000)
            request_id_var.reset(token)


# ---------- security headers (Phase 12, OWASP A05) ----------

_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(self), payment=(self)"),
    (b"cross-origin-opener-policy", b"same-origin"),
]
# JSON API responses are never cached by browsers or proxies (they carry personal data).
_NO_STORE = (b"cache-control", b"no-store")


class SecurityHeadersMiddleware:
    """Adds hardening headers to every API response; HSTS and the SPA's CSP are set by Nginx."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                for k, v in _SECURITY_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if is_api and b"cache-control" not in present:
                    headers.append(_NO_STORE)
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------- request metrics for /api/v1/metrics (Prometheus text format) ----------


class Metrics:
    """In-process counters; each API/worker process exposes its own (scrape every instance)."""

    BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

    def __init__(self) -> None:
        self.requests: dict[tuple[str, str], int] = {}
        self.latency = [0] * (len(self.BUCKETS) + 1)
        self.latency_sum = 0.0
        self.latency_count = 0
        self.started = time.time()

    def observe(self, method: str, status: int, seconds: float) -> None:
        key = (method, f"{status // 100}xx")
        self.requests[key] = self.requests.get(key, 0) + 1
        for i, b in enumerate(self.BUCKETS):
            if seconds <= b:
                self.latency[i] += 1
        self.latency[-1] += 1
        self.latency_sum += seconds
        self.latency_count += 1

    def render(self) -> str:
        lines = [
            "# HELP waitless_http_requests_total HTTP requests by method and status class.",
            "# TYPE waitless_http_requests_total counter",
        ]
        for (method, cls), n in sorted(self.requests.items()):
            lines.append(f'waitless_http_requests_total{{method="{method}",status="{cls}"}} {n}')
        lines += [
            "# HELP waitless_http_request_duration_seconds Request latency.",
            "# TYPE waitless_http_request_duration_seconds histogram",
        ]
        for b, n in zip(self.BUCKETS, self.latency, strict=False):
            lines.append(f'waitless_http_request_duration_seconds_bucket{{le="{b}"}} {n}')
        lines.append(f'waitless_http_request_duration_seconds_bucket{{le="+Inf"}} {self.latency[-1]}')
        lines.append(f"waitless_http_request_duration_seconds_sum {self.latency_sum:.6f}")
        lines.append(f"waitless_http_request_duration_seconds_count {self.latency_count}")
        lines += [
            "# HELP waitless_uptime_seconds Seconds since this process started.",
            "# TYPE waitless_uptime_seconds gauge",
            f"waitless_uptime_seconds {time.time() - self.started:.0f}",
        ]
        return "\n".join(lines) + "\n"


METRICS = Metrics()
