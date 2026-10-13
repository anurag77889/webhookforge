"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import events, health, subscriptions
from app.database import engine
from app.logging import configure_logging
from app.redis_client import close_redis_client


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    yield
    await close_redis_client()
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="WebhookForge",
        description="Reliable webhook delivery engine",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(events.router)
    application.include_router(subscriptions.router)
    return application


app = create_app()
