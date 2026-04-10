"""Unit tests for the image upload worker and helpers."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["EBAY_CLIENT_ID"] = "client-id"
os.environ["EBAY_DEV_ID"] = "dev-id"
os.environ["EBAY_CLIENT_SECRET"] = "client-secret"
os.environ["EBAY_REFRESH_TOKEN"] = "refresh-token"
os.environ["CATALOG_API_BASE_URL"] = "https://catalog.example.com"
os.environ["CATALOG_API_KEY"] = "catalog-api-key"
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest

import src.ebay.image_uploader as image_uploader
import src.workers.image_worker as image_worker


class _FakeResponse:
    """Minimal HTTP response double for image fetch tests."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content_type: str = "image/jpeg",
        content: bytes = b"x" * 2048,
    ) -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.content = content


class _FakeAsyncClient:
    """AsyncClient test double that returns a configurable GET response."""

    response = _FakeResponse()

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> _FakeAsyncClient:
        """Enter the async client context."""

        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Exit the async client context."""

        return None

    async def get(self, url: str) -> _FakeResponse:
        """Return the configured fake response for the requested URL."""

        return self.response


@pytest.mark.asyncio
async def test_fetch_validates_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject non-image content types from external image URLs."""

    _FakeAsyncClient.response = _FakeResponse(content_type="text/html")
    monkeypatch.setattr(image_uploader.httpx, "AsyncClient", _FakeAsyncClient)

    result = await image_worker.fetch_and_validate_image("https://example.com/page")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_validates_size_too_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject images that are smaller than the minimum upload threshold."""

    _FakeAsyncClient.response = _FakeResponse(content=b"x" * 500)
    monkeypatch.setattr(image_uploader.httpx, "AsyncClient", _FakeAsyncClient)

    result = await image_worker.fetch_and_validate_image("https://example.com/image.jpg")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return image bytes when the external response passes validation."""

    expected = b"x" * 4096
    _FakeAsyncClient.response = _FakeResponse(content=expected)
    monkeypatch.setattr(image_uploader.httpx, "AsyncClient", _FakeAsyncClient)

    result = await image_worker.fetch_and_validate_image("https://example.com/image.jpg")

    assert result == expected


@pytest.mark.asyncio
async def test_process_images_skips_failed_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not revise listing pictures when every image fetch fails."""

    repo = SimpleNamespace(log_sync_action=AsyncMock())

    monkeypatch.setattr(image_worker, "ListingRepository", lambda: repo)
    monkeypatch.setattr(
        image_worker,
        "get_settings",
        lambda: SimpleNamespace(ebay_sandbox_mode=True),
    )
    monkeypatch.setattr(
        image_worker,
        "fetch_and_validate_image",
        AsyncMock(return_value=None),
    )
    revise_mock = AsyncMock()
    monkeypatch.setattr(image_worker, "revise_listing_pictures", revise_mock)

    await image_worker.process_images(
        "ZE-BRK-001",
        "110589311637",
        [
            {"url": "https://example.com/image1.jpg", "position": 1},
            {"url": "https://example.com/image2.jpg", "position": 0},
        ],
    )

    revise_mock.assert_not_awaited()
