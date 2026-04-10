"""Cloud Run Pub/Sub push worker for eBay image uploads."""

from __future__ import annotations

import base64
import json
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import SyncAction
from src.db.repository import ListingRepository
from src.ebay.auth import get_ebay_token
from src.ebay.image_uploader import fetch_and_validate_image, upload_image_to_ebay
from src.ebay.trading_api import EbayTradingClient

app = FastAPI(title="ZEParts Image Worker")


class ImageJob(BaseModel):
    """Pub/Sub payload for image upload work."""

    sku: str
    ebay_item_id: str
    images: list[dict[str, Any]]


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a simple health response for Cloud Run probes."""

    return {"status": "healthy"}


@app.post("/pubsub/push")
async def pubsub_push(payload: dict) -> dict[str, str]:
    """Handle a Pub/Sub push message carrying an image job payload."""

    try:
        message = payload["message"]
        encoded_data = message["data"]
        decoded_data = base64.b64decode(encoded_data)
        job = ImageJob.model_validate_json(decoded_data)
        await process_images(job.sku, job.ebay_item_id, job.images)
    except (KeyError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _logger().exception("Image worker failed to process Pub/Sub message.")
        raise HTTPException(status_code=500, detail="internal server error") from exc

    return {"status": "ok"}


async def process_images(sku: str, ebay_item_id: str, images: list[dict]) -> None:
    """Fetch, upload, and attach external product images to an eBay listing."""

    repo = ListingRepository()
    settings = get_settings()
    ebay_urls: list[str] = []

    sorted_images = sorted(images, key=lambda image: int(image.get("position", 0)))[:12]

    for image in sorted_images:
        url = image.get("url")
        if not isinstance(url, str) or not url:
            _logger().warning(
                "Image job entry skipped due to invalid URL.",
                extra={"sku": sku, "image": image},
            )
            continue

        image_bytes = await fetch_and_validate_image(url)
        if image_bytes is None:
            _logger().warning(
                "Image fetch failed; skipping upload.",
                extra={"sku": sku, "url": url},
            )
            continue

        hosted_url = await upload_image_to_ebay(image_bytes, url)
        if hosted_url is None:
            _logger().warning(
                "eBay image upload failed; skipping image.",
                extra={"sku": sku, "url": url},
            )
            continue

        ebay_urls.append(hosted_url)

    if not ebay_urls:
        _logger().error(
            "Image worker could not upload any images.",
            extra={"sku": sku, "ebay_item_id": ebay_item_id},
        )
        return

    await revise_listing_pictures(ebay_item_id, ebay_urls)

    _logger().info(
        "Image worker uploaded listing images.",
        extra={
            "sku": sku,
            "ebay_item_id": ebay_item_id,
            "count": len(ebay_urls),
            "environment": "sandbox" if settings.ebay_sandbox_mode else "production",
        },
    )
    await repo.log_sync_action(
        sku,
        SyncAction.image_upload,
        success=True,
        ebay_item_id=ebay_item_id,
        detail=f"uploaded {len(ebay_urls)} images",
    )


async def revise_listing_pictures(ebay_item_id: str, picture_urls: list[str]) -> None:
    """Revise an eBay listing so it references eBay-hosted picture URLs."""

    client = EbayTradingClient()

    try:
        token = await get_ebay_token()
        picture_xml = "".join(
            f"<PictureURL>{escape(url)}</PictureURL>" for url in picture_urls
        )
        xml_payload = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<ReviseItemRequest xmlns="{client.XML_NAMESPACE}">'
            "<RequesterCredentials>"
            f"<eBayAuthToken>{escape(token)}</eBayAuthToken>"
            "</RequesterCredentials>"
            "<Item>"
            f"<ItemID>{escape(ebay_item_id)}</ItemID>"
            "<PictureDetails>"
            f"{picture_xml}"
            "</PictureDetails>"
            "</Item>"
            "</ReviseItemRequest>"
        )
        await client._post("ReviseItem", xml_payload)
    except Exception as exc:
        _logger().warning(
            "ReviseItem picture update failed.",
            extra={"ebay_item_id": ebay_item_id, "reason": str(exc)},
        )
        return

    _logger().info(
        "ReviseItem picture update succeeded.",
        extra={"ebay_item_id": ebay_item_id, "count": len(picture_urls)},
    )


__all__ = [
    "ImageJob",
    "app",
    "fetch_and_validate_image",
    "process_images",
    "revise_listing_pictures",
    "upload_image_to_ebay",
]
