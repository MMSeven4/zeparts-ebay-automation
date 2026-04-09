"""Cloud Run worker for daily eBay listing reconciliation."""

from __future__ import annotations

import base64

from fastapi import FastAPI, HTTPException

from src.catalog.client import CatalogClient
from src.catalog.models import Part
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import ListingStatus, SyncAction
from src.db.repository import ListingRepository
from src.ebay.trading_api import EbayTradingClient

app = FastAPI(title="ZEParts Sync Worker")


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a basic health response for Cloud Run probes."""

    return {"status": "healthy"}


@app.post("/pubsub/push")
async def pubsub_push(payload: dict) -> dict:
    """Handle scheduler-triggered Pub/Sub reconciliation jobs."""

    try:
        message = payload.get("message", {})
        attributes = message.get("attributes", {})
        encoded_data = message.get("data", "")
        if encoded_data:
            base64.b64decode(encoded_data)

        job_type = attributes.get("job_type", "full_sync")
        if job_type == "full_sync":
            summary = await run_full_sync()
            return {"status": "ok", "summary": summary}
        if job_type == "sku_sync":
            sku = attributes.get("sku")
            if not sku:
                raise ValueError("sku attribute is required for sku_sync jobs")
            await run_sku_sync(sku)
            return {"status": "ok", "sku": sku}

        raise ValueError(f"unsupported job_type: {job_type}")
    except Exception as exc:
        _logger().exception("Sync worker failed to process Pub/Sub message.")
        raise HTTPException(status_code=500, detail="internal server error") from exc


async def run_full_sync() -> dict[str, int]:
    """Reconcile all active listings against the current catalog state."""

    repo = ListingRepository()
    active_listings = await repo.get_active_listings()

    summary = {
        "checked": len(active_listings),
        "updated": 0,
        "ended": 0,
        "errors": 0,
    }

    for listing in active_listings:
        result = await reconcile_sku(listing.sku)
        if result == "updated":
            summary["updated"] += 1
        elif result == "ended":
            summary["ended"] += 1
        elif result == "error":
            summary["errors"] += 1

    _logger().info("Full sync complete", extra=summary)
    return summary


async def run_sku_sync(sku: str) -> None:
    """Fetch a single SKU from the catalog and reconcile its listing."""

    client_catalog = CatalogClient()
    part = await client_catalog.get_part(sku)
    await reconcile_sku(sku, part)


async def reconcile_sku(sku: str, part: Part | None = None) -> str:
    """Reconcile one SKU and return the outcome."""

    repo = ListingRepository()
    client_catalog = CatalogClient()
    client_ebay = EbayTradingClient()
    settings = get_settings()

    try:
        if part is None:
            part = await client_catalog.get_part(sku)

        existing = await repo.get_by_sku(sku)
        if existing is None:
            _logger().warning("no DB record for SKU", extra={"sku": sku})
            return "error"

        if part is None or part.available is False or part.stock_qty == 0:
            if existing.status == ListingStatus.active and existing.ebay_item_id:
                if not settings.dry_run:
                    await client_ebay.end_item(
                        existing.ebay_item_id,
                        reason="NotAvailable",
                    )
                await repo.update_status(sku, ListingStatus.ended)
                await repo.log_sync_action(
                    sku,
                    SyncAction.end,
                    success=True,
                    ebay_item_id=existing.ebay_item_id,
                    detail="ended: unavailable or zero stock",
                )
                _logger().info(
                    "Ended listing",
                    extra={"sku": sku, "item_id": existing.ebay_item_id},
                )
            return "ended"

        target_quantity = min(part.stock_qty, settings.listing_qty_cap)
        target_price = part.price_aud * settings.price_margin_multiplier
        qty_changed = existing.quantity != target_quantity
        price_changed = existing.price_aud is None or abs(
            existing.price_aud - target_price
        ) > 0.01

        if qty_changed or price_changed:
            new_qty = target_quantity if qty_changed else None
            new_price = target_price if price_changed else None

            if not settings.dry_run:
                await client_ebay.revise_inventory_status(
                    existing.ebay_item_id,
                    quantity=new_qty,
                    price=new_price,
                )
            await repo.upsert_listing(
                sku=sku,
                ebay_item_id=existing.ebay_item_id,
                status=ListingStatus.active,
                price_aud=part.price_aud,
                quantity=part.stock_qty,
            )
            await repo.mark_synced(sku)
            await repo.log_sync_action(
                sku,
                SyncAction.revise,
                success=True,
                ebay_item_id=existing.ebay_item_id,
                detail=f"qty_changed={qty_changed} price_changed={price_changed}",
            )
            _logger().info(
                "Updated listing",
                extra={
                    "sku": sku,
                    "qty_changed": qty_changed,
                    "price_changed": price_changed,
                },
            )
            return "updated"

        await repo.mark_synced(sku)
        return "unchanged"
    except Exception as exc:
        _logger().exception("Failed to reconcile SKU", extra={"sku": sku})
        await repo.log_sync_action(
            sku,
            SyncAction.sync_check,
            success=False,
            detail=str(exc),
        )
        return "error"
