"""Unit tests for the async listing repository."""

from __future__ import annotations

import os

os.environ["EBAY_CLIENT_ID"] = "client-id"
os.environ["EBAY_CLIENT_SECRET"] = "client-secret"
os.environ["EBAY_REFRESH_TOKEN"] = "refresh-token"
os.environ["CATALOG_API_BASE_URL"] = "https://catalog.example.com"
os.environ["CATALOG_API_KEY"] = "catalog-api-key"
os.environ["DB_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.db.repository as repository_module
from src.db.models import Base, EbayListing, ListingStatus, SyncAction, SyncLog
from src.db.repository import ListingRepository, get_session

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def test_db(monkeypatch: pytest.MonkeyPatch):
    """Create a fresh in-memory async SQLite database for each test."""

    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(repository_module, "engine", engine)
    monkeypatch.setattr(repository_module, "AsyncSessionLocal", session_factory)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.mark.asyncio
async def test_upsert_creates_new_listing(test_db) -> None:
    """Create a new listing row on first upsert."""

    repo = ListingRepository()

    await repo.upsert_listing(
        sku="ZE-001",
        ebay_item_id="12345",
        status=ListingStatus.active,
    )

    listing = await repo.get_by_sku("ZE-001")

    assert listing is not None
    assert listing.ebay_item_id == "12345"


@pytest.mark.asyncio
async def test_upsert_updates_existing(test_db) -> None:
    """Update an existing listing row on repeated upsert."""

    repo = ListingRepository()

    await repo.upsert_listing(
        sku="ZE-002",
        ebay_item_id="11111",
        status=ListingStatus.pending,
    )
    await repo.upsert_listing(
        sku="ZE-002",
        ebay_item_id="22222",
        status=ListingStatus.active,
    )

    listing = await repo.get_by_sku("ZE-002")

    assert listing is not None
    assert listing.ebay_item_id == "22222"
    assert listing.status == ListingStatus.active


@pytest.mark.asyncio
async def test_update_status_to_error(test_db) -> None:
    """Persist error status and error message updates."""

    repo = ListingRepository()

    await repo.upsert_listing(
        sku="ZE-003",
        ebay_item_id="33333",
        status=ListingStatus.pending,
    )
    await repo.update_status(
        sku="ZE-003",
        status=ListingStatus.error,
        error_message="listing failed",
    )

    listing = await repo.get_by_sku("ZE-003")

    assert listing is not None
    assert listing.status == ListingStatus.error
    assert listing.error_message == "listing failed"


@pytest.mark.asyncio
async def test_log_sync_action_inserts_row(test_db) -> None:
    """Insert a sync log row for an outbound sync action."""

    repo = ListingRepository()

    await repo.log_sync_action(
        sku="ZE-004",
        action=SyncAction.create,
        success=True,
        ebay_item_id="44444",
        detail="created successfully",
    )

    async with get_session() as session:
        result = await session.execute(select(SyncLog).where(SyncLog.sku == "ZE-004"))
        log_row = result.scalar_one_or_none()

    assert log_row is not None
    assert log_row.action == SyncAction.create
    assert log_row.ebay_item_id == "44444"


@pytest.mark.asyncio
async def test_get_active_listings(test_db) -> None:
    """Return only listings currently marked active."""

    repo = ListingRepository()

    await repo.upsert_listing(
        sku="ZE-005",
        ebay_item_id="50001",
        status=ListingStatus.active,
    )
    await repo.upsert_listing(
        sku="ZE-006",
        ebay_item_id="50002",
        status=ListingStatus.active,
    )
    await repo.upsert_listing(
        sku="ZE-007",
        ebay_item_id="50003",
        status=ListingStatus.ended,
    )

    active_listings = await repo.get_active_listings()

    assert len(active_listings) == 2
    assert {listing.sku for listing in active_listings} == {"ZE-005", "ZE-006"}
