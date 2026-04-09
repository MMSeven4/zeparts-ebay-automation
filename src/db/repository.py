"""Async repository helpers for listing persistence and audit logging."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings
from src.db.models import EbayListing, ListingStatus, SyncAction, SyncLog

_settings = get_settings()
_engine_kwargs: dict[str, object] = {
    "echo": False,
    "pool_pre_ping": True,
}
if not _settings.db_url.startswith("sqlite"):
    _engine_kwargs.update(
        {
            "pool_size": 5,
            "max_overflow": 10,
        }
    )

engine = create_async_engine(_settings.db_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a managed async session with commit-or-rollback semantics."""

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class ListingRepository:
    """Repository for eBay listings and sync audit records."""

    async def get_by_sku(self, sku: str) -> EbayListing | None:
        """Return the listing row for a SKU, if one exists."""

        async with get_session() as session:
            result = await session.execute(
                select(EbayListing).where(EbayListing.sku == sku)
            )
            return result.scalar_one_or_none()

    async def upsert_listing(
        self,
        sku: str,
        ebay_item_id: str,
        status: ListingStatus,
        title: str | None = None,
        price_aud: float | None = None,
        quantity: int | None = None,
    ) -> EbayListing:
        """Insert or update an eBay listing row for the given SKU."""

        async with get_session() as session:
            result = await session.execute(
                select(EbayListing).where(EbayListing.sku == sku)
            )
            listing = result.scalar_one_or_none()

            if listing is None:
                listing = EbayListing(
                    sku=sku,
                    ebay_item_id=ebay_item_id,
                    status=status,
                    title=title,
                    price_aud=price_aud,
                    quantity=quantity,
                )
                session.add(listing)
            else:
                listing.ebay_item_id = ebay_item_id
                listing.status = status
                if title is not None:
                    listing.title = title
                if price_aud is not None:
                    listing.price_aud = price_aud
                if quantity is not None:
                    listing.quantity = quantity
                listing.updated_at = datetime.utcnow()

            await session.flush()
            return listing

    async def update_status(
        self,
        sku: str,
        status: ListingStatus,
        error_message: str | None = None,
    ) -> None:
        """Update the status and optional error message for a listing."""

        async with get_session() as session:
            result = await session.execute(
                select(EbayListing).where(EbayListing.sku == sku)
            )
            listing = result.scalar_one_or_none()
            if listing is None:
                return

            listing.status = status
            if error_message is not None:
                listing.error_message = error_message
            listing.updated_at = datetime.utcnow()

    async def mark_synced(self, sku: str) -> None:
        """Set the last synced timestamp for a listing."""

        async with get_session() as session:
            result = await session.execute(
                select(EbayListing).where(EbayListing.sku == sku)
            )
            listing = result.scalar_one_or_none()
            if listing is None:
                return

            listing.last_synced_at = datetime.utcnow()
            listing.updated_at = datetime.utcnow()

    async def get_active_listings(self) -> list[EbayListing]:
        """Return all listings currently marked as active."""

        async with get_session() as session:
            result = await session.execute(
                select(EbayListing).where(EbayListing.status == ListingStatus.active)
            )
            return list(result.scalars().all())

    async def log_sync_action(
        self,
        sku: str,
        action: SyncAction,
        success: bool,
        ebay_item_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Insert a sync audit log row."""

        async with get_session() as session:
            session.add(
                SyncLog(
                    sku=sku,
                    action=action,
                    success=success,
                    ebay_item_id=ebay_item_id,
                    detail=detail,
                )
            )
