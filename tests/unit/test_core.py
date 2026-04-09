"""Unit tests for core settings, logging, and retry helpers."""

from __future__ import annotations

import logging

import httpx
import pytest
from tenacity import wait_none

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.retry import with_retry
import src.core.retry as retry_module


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load settings from env vars and verify default values."""

    monkeypatch.setenv("EBAY_CLIENT_ID", "client-id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("CATALOG_API_BASE_URL", "https://catalog.example.com")
    monkeypatch.setenv("CATALOG_API_KEY", "catalog-api-key")
    monkeypatch.setenv("DB_URL", "postgresql+asyncpg://user:pass@localhost/db")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.dry_run is False
    assert settings.listing_qty_cap == 99
    assert settings.price_margin_multiplier == 1.0

    get_settings.cache_clear()


def test_get_logger_returns_logger() -> None:
    """Return a configured logger instance."""

    import os

    os.environ["EBAY_CLIENT_ID"] = "client-id"
    os.environ["EBAY_CLIENT_SECRET"] = "client-secret"
    os.environ["EBAY_REFRESH_TOKEN"] = "refresh-token"
    os.environ["CATALOG_API_BASE_URL"] = "https://catalog.example.com"
    os.environ["CATALOG_API_KEY"] = "catalog-api-key"
    os.environ["DB_URL"] = "postgresql+asyncpg://user:pass@localhost/db"
    get_settings.cache_clear()
    logger = get_logger("test")

    assert isinstance(logger, logging.Logger)


@pytest.mark.asyncio
async def test_with_retry_raises_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry three times and then re-raise the last exception."""

    attempts = 0

    monkeypatch.setattr(retry_module, "_get_wait_strategy", lambda: wait_none())

    async def always_fails() -> None:
        nonlocal attempts
        attempts += 1
        raise httpx.NetworkError("network unavailable")

    wrapped = with_retry(always_fails)

    with pytest.raises(httpx.NetworkError):
        await wrapped()

    assert attempts == 3
