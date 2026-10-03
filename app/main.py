"""Main entry point for the Real-Time Feature Store FastAPI application.

Configures application lifespan, routing, global logging, and exception handling.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.services.redis_client import redis_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown events for external connections."""
    logger.info("Initializing Real-Time Feature Store API application...")
    await redis_client.connect()
    yield
    logger.info("Shutting down Real-Time Feature Store API application...")
    await redis_client.close()


app = FastAPI(
    title="Real-Time Feature Store API",
    description=(
        "Production-grade, low-latency online feature store backend with Redis "
        "designed for machine learning inference serving."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler to prevent leaking internal stack traces or secrets."""
    logger.exception("Unhandled server error processing request %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(router)
