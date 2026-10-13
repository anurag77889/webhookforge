"""Active dependency health checks."""

import asyncio
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.celery_app import celery_app
from app.database import SessionFactory
from app.redis_client import redis_client

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    checks: dict[str, str | int] = {}

    try:
        async with SessionFactory() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "connected"
    except Exception as exc:  # pragma: no cover - depends on deployed infrastructure
        checks["postgres"] = f"error: {exc.__class__.__name__}"

    try:
        await redis_client.ping()
        checks["redis"] = "connected"
    except Exception as exc:  # pragma: no cover - depends on deployed infrastructure
        checks["redis"] = f"error: {exc.__class__.__name__}"

    try:
        inspector = celery_app.control.inspect(timeout=1.0)
        active = await asyncio.to_thread(inspector.active)
        checks["celery_workers"] = len(active or {})
    except Exception:  # pragma: no cover - broker-dependent
        checks["celery_workers"] = 0

    dependencies_healthy = all(checks[name] == "connected" for name in ("postgres", "redis"))
    status = "healthy" if dependencies_healthy and checks["celery_workers"] else "degraded"
    return {"status": status, **checks}
