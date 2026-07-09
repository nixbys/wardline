from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from cranus.api.routers import audit, entity_review, feedback, health, query, session
from cranus.common.config import get_settings
from cranus.common.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.environment)
    logger.info("startup", environment=settings.environment, llm_mode=settings.llm_client_mode)

    from cranus.graph.repository import ensure_constraints

    try:
        ensure_constraints()
    except Exception as exc:  # noqa: BLE001 - Neo4j being briefly unavailable shouldn't crash the API
        logger.error("startup.neo4j_constraints_failed", error=str(exc))

    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="cranus", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(session.router)
    app.include_router(audit.router)
    app.include_router(feedback.router)
    app.include_router(entity_review.router)
    return app


app = create_app()
