from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from wardline.api.routers import (
    admin_connectors,
    admin_engagements,
    admin_iceberg,
    admin_users,
    audit,
    auth,
    billing,
    entity_review,
    feedback,
    health,
    query,
    session,
    upload,
)
from wardline.common.config import get_settings
from wardline.common.logging import configure_logging, get_logger
from wardline.common.observability import configure_observability
from wardline.governance.rate_limit import limiter

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.environment)
    logger.info("startup", environment=settings.environment, llm_mode=settings.llm_client_mode)

    from wardline.graph.repository import ensure_constraints

    try:
        ensure_constraints()
    except Exception as exc:  # Neo4j being briefly unavailable shouldn't crash the API
        logger.error("startup.neo4j_constraints_failed", error=str(exc))

    yield
    logger.info("shutdown")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline response headers for an API with no browser-rendered pages of
    its own: still worth setting so a browser hitting these endpoints
    directly (e.g. an error page, a misconfigured proxy) doesn't sniff
    content types or get framed/cached unexpectedly.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


def create_app() -> FastAPI:
    # debug=False (the default) is load-bearing, not just an unset knob:
    # Starlette's ServerErrorMiddleware only suppresses tracebacks from
    # unhandled exceptions when debug is False. Set explicitly so it can't
    # be silently flipped by a future FastAPI default change.
    app = FastAPI(title="wardline", version="0.1.0", lifespan=lifespan, debug=False)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    configure_observability(app, get_settings())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            # Pass the exception object explicitly rather than `True`: this handler
            # runs as an ASGI callback, not inside a literal `except` block, so
            # relying on the ambient sys.exc_info() is not guaranteed to work.
            exc_info=exc,
        )
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(billing.router)
    app.include_router(query.router)
    app.include_router(session.router)
    app.include_router(audit.router)
    app.include_router(feedback.router)
    app.include_router(entity_review.router)
    app.include_router(admin_users.router)
    app.include_router(admin_connectors.router)
    app.include_router(admin_engagements.router)
    app.include_router(admin_iceberg.router)
    app.include_router(upload.router)
    return app


app = create_app()
