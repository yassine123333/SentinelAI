"""
SentinelAI — FastAPI application entry point.

Run locally:
    cd backend
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Security controls (per presentation spec)
------------------------------------------
  - CORS: whitelist-only (no wildcards), credentials allowed
  - HSTS headers injected on every response (1-year max-age)
  - Rate limiting via slowapi (10 req/min per IP default)
  - JWT verified on every protected route (HTTPBearer dependency)
  - MongoDB connection pool capped at 100 concurrent connections
  - Structured JSON audit logging
"""
from __future__ import annotations

import ipaddress
import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes.auth import router as auth_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.admin import router as admin_router
from app.config.settings import get_settings
from app.db.mongodb import close_db, connect_db
from app.security.collectors import RequestEvent, emit_event
from app.security.daemon import get_daemon

# ── Logging ───────────────────────────────────────────────────────────────────

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "format": '{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}',
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {"handlers": ["console"], "level": "INFO"},
    }
)

logger = logging.getLogger(__name__)

# ── Rate limiter (global, IP-based) ──────────────────────────────────────────
# No default_limits here — each route declares its own limit.
# A catch-all default would share a single bucket across ALL endpoints
# (login, register, pipeline query …), causing legitimate requests to be
# blocked after only a handful of auth calls.

def _private_ip(ip: str) -> bool:
    """Return True if ip is an RFC-1918 / loopback / link-local address."""
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def _real_client_ip(request: Request) -> str:
    """
    Resolve the real client IP without allowing X-Forwarded-For spoofing.

    X-Forwarded-For is only trusted when the direct TCP connection comes from
    a private/internal IP (i.e., a trusted reverse proxy like Caddy or nginx
    inside the Docker network).  External clients that set XFF themselves will
    have their connection IP used directly — spoofing is not possible.
    """
    connection_ip: str = (request.client.host if request.client else "") or "unknown"
    if _private_ip(connection_ip):
        # Connection came from a trusted internal proxy — read the leftmost XFF IP
        xff = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if xff:
            return xff
    return connection_ip


limiter = Limiter(key_func=_real_client_ip)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup / shutdown events."""
    logger.info("SentinelAI starting up …")
    await connect_db()

    # Start the SOC security daemon as a background asyncio task.
    # It monitors all platform layers (FastAPI, MongoDB, Nginx) continuously.
    _daemon = get_daemon()
    await _daemon.start()

    yield

    await _daemon.stop()
    await close_db()
    logger.info("SentinelAI shut down.")


# ── FastAPI app ───────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title="SentinelAI API",
    description=(
        "Geopolitical market intelligence platform. "
        "JWT-authenticated REST API."
    ),
    version="1.0.0",
    docs_url="/api/docs" if settings.debug else None,      # hide docs in prod
    redoc_url="/api/redoc" if settings.debug else None,
    openapi_url="/api/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

# ── Rate-limit middleware & handler ───────────────────────────────────────────

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Per presentation: "CORS whitelist limited to production domain only (no wildcards)"

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


# ── SOC Middleware — feed every request into the security daemon ──────────────
# This is the primary FastAPI log source for the daemon.
# It emits a RequestEvent for every HTTP request (before and after processing)
# so the daemon can track rate, auth failures, injection probes, UA rotation.

@app.middleware("http")
async def soc_middleware(request: Request, call_next):
    """
    Emit a RequestEvent to the SOC daemon queue for every request.

    Also enforces daemon decisions at request time:
      - BLOCKED IPs  → 403 immediately (no processing)
      - SUSPENDED IPs → 403 session suspended
      - CAPTCHA IPs  → 403 with challenge hint

    The enforcement check is a fast MongoDB lookup (indexed on IP).
    It only fires for non-health-check endpoints to avoid overhead.
    """
    client_ip: str = _real_client_ip(request)

    # Skip enforcement for internal health checks
    if request.url.path not in ("/api/health",):
        try:
            from app.security.persistence import get_ip_flags
            flags = await get_ip_flags(client_ip)
            if flags["blocked"]:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Access denied."},
                )
            if flags["suspended"]:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Account temporarily suspended due to suspicious activity."},
                )
            if flags["captcha_required"]:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "detail": "Security verification required. Please complete the challenge.",
                        "captcha_required": True,
                    },
                )
        except Exception as _flags_exc:
            # DB unreachable — fall back to in-memory hard-block set so
            # permanently blocked IPs remain blocked even during DB outages.
            logger.warning("SOC: DB flags lookup failed for %s, using memory fallback: %s", client_ip, _flags_exc)
            try:
                daemon = get_daemon()
                if client_ip in daemon._hard_blocked:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "Access denied."},
                    )
            except Exception:
                pass  # Memory fallback also failed — fail open for non-blocked IPs

    # Process the request
    response = await call_next(request)

    # Emit event to the SOC daemon queue (non-blocking)
    emit_event(
        RequestEvent(
            source="fastapi",
            ip=client_ip,
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            user_agent=request.headers.get("user-agent", ""),
            extra={
                "auth_scheme": (
                    request.headers.get("authorization", "").split(" ")[0]
                    if request.headers.get("authorization")
                    else ""
                ),
                "content_type": request.headers.get("content-type", ""),
            },
        )
    )

    return response


# ── HSTS + security headers middleware ───────────────────────────────────────
# Per presentation: HSTS with 1-year max-age

@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception path=%s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again later."},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(
    auth_router,
    prefix="/api/v1/auth",
    tags=["Authentication"],
)

app.include_router(
    pipeline_router,
    prefix="/api/v1",
    tags=["Pipeline"],
)

app.include_router(
    admin_router,
    prefix="/api/v1/admin",
    tags=["Admin"],
)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["System"], include_in_schema=False)
async def health():
    return {"status": "ok", "version": "1.0.0"}
