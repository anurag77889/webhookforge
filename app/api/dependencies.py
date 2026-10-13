"""Shared FastAPI dependencies."""

import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.config import settings


async def require_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Require the configured API key on mutating API endpoints."""
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
