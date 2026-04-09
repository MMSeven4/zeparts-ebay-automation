"""Unit tests for eBay OAuth token management."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import src.ebay.auth as auth_module
from src.ebay.auth import EbayTokenManager


class _FakeResponse:
    """Minimal async HTTP response double for token refresh tests."""

    def __init__(
        self,
        *,
        token: str = "test-token",
        expires_in: int = 3600,
        status_code: int = 200,
    ) -> None:
        self.status_code = status_code
        self._payload = {
            "access_token": token,
            "expires_in": expires_in,
        }

    def raise_for_status(self) -> None:
        """Simulate a successful HTTP response."""

        return None

    def json(self) -> dict:
        """Return the fake JSON token payload."""

        return self._payload


class _FakeAsyncClient:
    """AsyncClient test double that records POST calls."""

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _FakeAsyncClient:
        """Enter the async client context."""

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async client context."""

        return None

    async def post(self, url: str, *, headers: dict, data: dict) -> _FakeResponse:
        """Record a token refresh request and return a fake response."""

        _POST_CALLS.append(
            {
                "url": url,
                "headers": headers,
                "data": data,
            }
        )
        return _FakeResponse()


_POST_CALLS: list[dict] = []


def _settings(*, sandbox: bool = False) -> SimpleNamespace:
    """Return a lightweight settings object for token manager tests."""

    return SimpleNamespace(
        ebay_client_id="client-id",
        ebay_client_secret="client-secret",
        ebay_refresh_token="refresh-token",
        ebay_sandbox_mode=sandbox,
    )


@pytest.mark.asyncio
async def test_get_token_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the cached token when it remains valid for more than five minutes."""

    _POST_CALLS.clear()
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeAsyncClient)

    manager = EbayTokenManager()

    first_token = await manager.get_token()
    second_token = await manager.get_token()

    assert first_token == "test-token"
    assert second_token == "test-token"
    assert len(_POST_CALLS) == 1


@pytest.mark.asyncio
async def test_token_refresh_on_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refresh the token when the cached expiry is already in the past."""

    _POST_CALLS.clear()
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings())
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeAsyncClient)

    auth_module.token_manager._token = "expired-token"
    auth_module.token_manager._expires_at = datetime.utcnow() - timedelta(seconds=1)

    refreshed_token = await auth_module.token_manager.get_token()

    assert refreshed_token == "test-token"
    assert len(_POST_CALLS) == 1


@pytest.mark.asyncio
async def test_sandbox_url_used_when_sandbox_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post token refresh requests to the sandbox endpoint when enabled."""

    _POST_CALLS.clear()
    monkeypatch.setattr(auth_module, "get_settings", lambda: _settings(sandbox=True))
    monkeypatch.setattr(auth_module.httpx, "AsyncClient", _FakeAsyncClient)

    manager = EbayTokenManager()

    await manager.get_token()

    assert _POST_CALLS[0]["url"] == manager.SANDBOX_TOKEN_URL
