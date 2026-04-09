"""SQLAlchemy ORM models for eBay listing state and sync logs."""

from __future__ import annotations

from datetime import datetime
import enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class ListingStatus(str, enum.Enum):
    """Current lifecycle status of an eBay listing record."""

    pending = "pending"
    active = "active"
    ended = "ended"
    error = "error"


class SyncAction(str, enum.Enum):
    """Supported sync actions that are logged for auditing."""

    create = "create"
    revise = "revise"
    end = "end"
    image_upload = "image_upload"
    sync_check = "sync_check"


class EbayListing(Base):
    """Persistent record of an eBay listing mapped to an internal SKU."""

    __tablename__ = "ebay_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )
    ebay_item_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[ListingStatus] = mapped_column(
        SAEnum(ListingStatus),
        default=ListingStatus.pending,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_aud: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class SyncLog(Base):
    """Audit trail for outbound listing and sync operations."""

    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    action: Mapped[SyncAction] = mapped_column(SAEnum(SyncAction), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ebay_item_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
