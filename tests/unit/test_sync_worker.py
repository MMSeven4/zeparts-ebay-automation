"""Unit tests for the sync reconciliation worker."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ["EBAY_CLIENT_ID"] = "client-id"
os.environ["EBAY_CLIENT_SECRET"] = "client-secret"
os.environ["EBAY_REFRESH_TOKEN"] = "refresh-token"
os.environ["CATALOG_API_BASE_URL"] = "https://catalog.example.com"
os.environ["CATALOG_API_KEY"] = "catalog-api-key"
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest

import src.workers.sync_worker as sync_worker
from src.catalog.models import Part
from src.db.models import ListingStatus


def _settings(*, dry_run: bool = False) -> SimpleNamespace:
    """Return a lightweight settings object for sync worker tests."""

    return SimpleNamespace(
        dry_run=dry_run,
        listing_qty_cap=99,
        price_margin_multiplier=1.0,
    )


def _part(*, available: bool = True, stock_qty: int = 12, price_aud: float = 129.95) -> Part:
    """Build a valid Part model for sync tests."""

    return Part.model_validate(
        {
            "sku": "ZE-BRK-001",
            "brand": "Bendix",
            "part_name": "Front Brake Pad Set",
            "part_category": "Brake Pads",
            "year_range": "2015-2019",
            "make": "Toyota",
            "model": "Hilux",
            "condition": "new",
            "price_aud": price_aud,
            "stock_qty": stock_qty,
            "available": available,
            "images": [{"url": "https://example.com/image-1.jpg", "position": 0}],
        }
    )


def _listing(
    *,
    status: ListingStatus = ListingStatus.active,
    quantity: int | None = 12,
    price_aud: float | None = 129.95,
) -> SimpleNamespace:
    """Return a minimal listing-like object for repository mocks."""

    return SimpleNamespace(
        sku="ZE-BRK-001",
        ebay_item_id="1234567890",
        status=status,
        quantity=quantity,
        price_aud=price_aud,
    )


@pytest.mark.asyncio
async def test_reconcile_ends_unavailable_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End an active listing when the part becomes unavailable."""

    repo = SimpleNamespace(
        get_by_sku=AsyncMock(return_value=_listing()),
        update_status=AsyncMock(),
        log_sync_action=AsyncMock(),
        upsert_listing=AsyncMock(),
        mark_synced=AsyncMock(),
    )
    ebay_client = SimpleNamespace(
        end_item=AsyncMock(),
        revise_inventory_status=AsyncMock(),
    )
    catalog_client = SimpleNamespace(get_part=AsyncMock())

    monkeypatch.setattr(sync_worker, "ListingRepository", lambda: repo)
    monkeypatch.setattr(sync_worker, "EbayTradingClient", lambda: ebay_client)
    monkeypatch.setattr(sync_worker, "CatalogClient", lambda: catalog_client)
    monkeypatch.setattr(sync_worker, "get_settings", lambda: _settings())

    result = await sync_worker.reconcile_sku("ZE-BRK-001", _part(available=False))

    assert result == "ended"
    ebay_client.end_item.assert_awaited_once_with(
        "1234567890",
        reason="NotAvailable",
    )
    repo.update_status.assert_awaited_once_with(
        "ZE-BRK-001",
        ListingStatus.ended,
    )


@pytest.mark.asyncio
async def test_reconcile_updates_on_qty_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revise inventory status when quantity drift is detected."""

    repo = SimpleNamespace(
        get_by_sku=AsyncMock(return_value=_listing(quantity=10, price_aud=129.95)),
        update_status=AsyncMock(),
        log_sync_action=AsyncMock(),
        upsert_listing=AsyncMock(),
        mark_synced=AsyncMock(),
    )
    ebay_client = SimpleNamespace(
        end_item=AsyncMock(),
        revise_inventory_status=AsyncMock(),
    )
    catalog_client = SimpleNamespace(get_part=AsyncMock())

    monkeypatch.setattr(sync_worker, "ListingRepository", lambda: repo)
    monkeypatch.setattr(sync_worker, "EbayTradingClient", lambda: ebay_client)
    monkeypatch.setattr(sync_worker, "CatalogClient", lambda: catalog_client)
    monkeypatch.setattr(sync_worker, "get_settings", lambda: _settings())

    result = await sync_worker.reconcile_sku("ZE-BRK-001", _part(stock_qty=50))

    assert result == "updated"
    ebay_client.revise_inventory_status.assert_awaited_once_with(
        "1234567890",
        quantity=50,
        price=None,
    )


@pytest.mark.asyncio
async def test_reconcile_unchanged_when_no_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mark a listing synced without eBay calls when no drift exists."""

    repo = SimpleNamespace(
        get_by_sku=AsyncMock(return_value=_listing(quantity=12, price_aud=129.95)),
        update_status=AsyncMock(),
        log_sync_action=AsyncMock(),
        upsert_listing=AsyncMock(),
        mark_synced=AsyncMock(),
    )
    ebay_client = SimpleNamespace(
        end_item=AsyncMock(),
        revise_inventory_status=AsyncMock(),
    )
    catalog_client = SimpleNamespace(get_part=AsyncMock())

    monkeypatch.setattr(sync_worker, "ListingRepository", lambda: repo)
    monkeypatch.setattr(sync_worker, "EbayTradingClient", lambda: ebay_client)
    monkeypatch.setattr(sync_worker, "CatalogClient", lambda: catalog_client)
    monkeypatch.setattr(sync_worker, "get_settings", lambda: _settings())

    result = await sync_worker.reconcile_sku("ZE-BRK-001", _part(stock_qty=12))

    assert result == "unchanged"
    ebay_client.end_item.assert_not_awaited()
    ebay_client.revise_inventory_status.assert_not_awaited()
    repo.mark_synced.assert_awaited_once_with("ZE-BRK-001")


@pytest.mark.asyncio
async def test_reconcile_returns_error_when_no_db_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return an error outcome when the SKU has no DB listing record."""

    repo = SimpleNamespace(
        get_by_sku=AsyncMock(return_value=None),
        update_status=AsyncMock(),
        log_sync_action=AsyncMock(),
        upsert_listing=AsyncMock(),
        mark_synced=AsyncMock(),
    )
    ebay_client = SimpleNamespace(
        end_item=AsyncMock(),
        revise_inventory_status=AsyncMock(),
    )
    catalog_client = SimpleNamespace(get_part=AsyncMock())

    monkeypatch.setattr(sync_worker, "ListingRepository", lambda: repo)
    monkeypatch.setattr(sync_worker, "EbayTradingClient", lambda: ebay_client)
    monkeypatch.setattr(sync_worker, "CatalogClient", lambda: catalog_client)
    monkeypatch.setattr(sync_worker, "get_settings", lambda: _settings())

    result = await sync_worker.reconcile_sku("ZE-BRK-001", _part())

    assert result == "error"
