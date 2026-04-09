"""Catalog ingestion flows that publish downstream listing jobs."""

from __future__ import annotations

from google.cloud import pubsub_v1

from src.catalog.client import CatalogClient
from src.catalog.models import CatalogPage, Part
from src.core.config import get_settings
from src.core.logging import get_logger


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def _publisher() -> pubsub_v1.PublisherClient:
    """Create a Pub/Sub publisher client."""

    return pubsub_v1.PublisherClient()


async def ingest_full_catalog(dry_run: bool = False) -> dict[str, int]:
    """Fetch the full catalog and publish all parts to the listing topic."""

    client = CatalogClient()
    page_number = 1
    total_fetched = 0
    published = 0
    errors = 0

    while True:
        page: CatalogPage = await client.get_page(page=page_number)
        total_fetched += len(page.parts)

        for part in page.parts:
            try:
                publish_listing_job(part, dry_run=dry_run)
            except Exception:
                errors += 1
                _logger().exception(
                    "Failed to publish listing job.",
                    extra={"sku": part.sku, "page": page_number},
                )
            else:
                published += 1

        if not page.has_next:
            break
        page_number += 1

    summary = {
        "total_fetched": total_fetched,
        "published": published,
        "errors": errors,
    }
    _logger().info("Full catalog ingestion complete", extra=summary)
    return summary


async def ingest_single_sku(sku: str, dry_run: bool = False) -> bool:
    """Fetch and publish a single catalog SKU."""

    client = CatalogClient()
    part = await client.get_part(sku)
    if part is None:
        _logger().warning("SKU not found", extra={"sku": sku})
        return False

    publish_listing_job(part, dry_run=dry_run)
    return True


def publish_listing_job(part: Part, dry_run: bool = False) -> None:
    """Publish a catalog part payload to the listing jobs topic."""

    settings = get_settings()
    payload = part.model_dump_json().encode("utf-8")

    if dry_run:
        _logger().info(
            "Dry run listing payload",
            extra={"sku": part.sku, "payload": part.model_dump(mode="json")},
        )
        return

    publisher = _publisher()
    topic_path = publisher.topic_path(
        settings.pubsub_project,
        settings.pubsub_listing_topic,
    )
    publish_future = publisher.publish(
        topic_path,
        payload,
        sku=part.sku,
        source="ingestion",
    )
    publish_future.result(timeout=30)

