"""Cloud Run Pub/Sub push worker for eBay listing creation and revision."""

from __future__ import annotations

import base64
import json

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from src.catalog.models import Part
from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import ListingStatus, SyncAction
from src.db.repository import ListingRepository
from src.ebay.listing_builder import build_listing_payload, build_title
from src.ebay.trading_api import EbayTradingClient

app = FastAPI(title="ZEParts Listing Worker")


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple health response for Cloud Run probes."""

    return {"status": "healthy"}


@app.post("/pubsub/push")
async def pubsub_push(payload: dict) -> dict[str, str]:
    """Handle a Pub/Sub push message carrying a serialized Part payload."""

    try:
        message = payload["message"]
        encoded_data = message["data"]
        decoded_data = base64.b64decode(encoded_data)
        part = Part.model_validate_json(decoded_data)
        await process_listing(part)
    except (KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _logger().exception("Listing worker failed to process Pub/Sub message.")
        raise HTTPException(status_code=500, detail="internal server error") from exc

    return {"status": "ok"}


async def process_listing(part: Part) -> None:
    """Create or revise an eBay listing from a catalog part payload."""

    settings = get_settings()
    repo = ListingRepository()
    existing = await repo.get_by_sku(part.sku)
    xml_payload = await build_listing_payload(part)

    if settings.dry_run:
        _logger().info(
            "Dry run listing worker payload",
            extra={"sku": part.sku, "title": build_title(part)},
        )
        return

    client = EbayTradingClient()

    try:
        if (
            existing is not None
            and existing.status == ListingStatus.active
            and existing.ebay_item_id
        ):
            ebay_item_id = await client.revise_item(
                existing.ebay_item_id,
                {"sku": part.sku},
            )
            action = SyncAction.revise
        else:
            ebay_item_id = await client.add_item_xml(xml_payload)
            action = SyncAction.create

        await repo.upsert_listing(
            sku=part.sku,
            ebay_item_id=ebay_item_id,
            status=ListingStatus.active,
            title=build_title(part),
            price_aud=part.price_aud,
            quantity=min(part.stock_qty, settings.listing_qty_cap),
        )
        await repo.mark_synced(part.sku)
        await repo.log_sync_action(
            sku=part.sku,
            action=action,
            success=True,
            ebay_item_id=ebay_item_id,
            detail=f"{action.value} listing succeeded",
        )
        _logger().info(
            "Listing worker processed part",
            extra={
                "sku": part.sku,
                "action": action.value,
                "item_id": ebay_item_id,
            },
        )
    except Exception as exc:
        await repo.update_status(
            sku=part.sku,
            status=ListingStatus.error,
            error_message=str(exc),
        )
        await repo.log_sync_action(
            sku=part.sku,
            action=SyncAction.revise
            if existing is not None and existing.ebay_item_id
            else SyncAction.create,
            success=False,
            ebay_item_id=existing.ebay_item_id if existing else None,
            detail=str(exc),
        )
        raise
