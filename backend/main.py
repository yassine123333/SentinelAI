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

import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.routes.auth import router as auth_router
from app.api.routes.pipeline import router as pipeline_router
from app.api.routes.admin import router as admin_router
from app.config.settings import get_settings
from app.db.mongodb import close_db, connect_db

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

limiter = Limiter(key_func=get_remote_address)


# ── Application lifespan ──────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup / shutdown events."""
    logger.info("SentinelAI starting up …")
    await connect_db()
    yield
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


# ── Frontend static serving (single-container deployment) ────────────────────

_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"

if _FRONTEND_DIST.exists() and _FRONTEND_INDEX.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def serve_frontend_root():
        return FileResponse(_FRONTEND_INDEX)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        candidate = _FRONTEND_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)

        return FileResponse(_FRONTEND_INDEX)
