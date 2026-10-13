"""Tests for the write-endpoint API key dependency."""

import pytest
from fastapi import HTTPException

from app.api.dependencies import require_api_key


async def test_require_api_key_accepts_matching_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.dependencies.settings.API_KEY", "expected-key")

    await require_api_key("expected-key")


@pytest.mark.parametrize("provided_key", [None, "incorrect-key"])
async def test_require_api_key_rejects_missing_or_invalid_keys(
    monkeypatch: pytest.MonkeyPatch, provided_key: str | None
) -> None:
    monkeypatch.setattr("app.api.dependencies.settings.API_KEY", "expected-key")

    with pytest.raises(HTTPException) as error:
        await require_api_key(provided_key)

    assert error.value.status_code == 401
