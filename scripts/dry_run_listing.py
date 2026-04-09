"""Run a local dry-run smoke test for the listing builder."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

os.environ.setdefault("EBAY_CLIENT_ID", "dry-run-client-id")
os.environ.setdefault("EBAY_CLIENT_SECRET", "dry-run-secret")
os.environ.setdefault("EBAY_REFRESH_TOKEN", "dry-run-token")
os.environ.setdefault("CATALOG_API_BASE_URL", "https://example.com")
os.environ.setdefault("CATALOG_API_KEY", "dry-run-key")
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DRY_RUN", "true")

from src.catalog.models import Part
from src.core.config import get_settings
from src.ebay.category_mapper import get_category_id
from src.ebay.listing_builder import (
    CONDITION_MAP,
    DEFAULT_CONDITION_ID,
    build_description_html,
    build_item_specifics,
    build_listing_payload,
    build_title,
)


async def main() -> None:
    """Load a sample part and print a formatted dry-run listing report."""

    fixture_path = (
        pathlib.Path(__file__).parent.parent
        / "tests"
        / "fixtures"
        / "sample_parts.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))[0]
    payload["images"] = [
        {"url": url, "position": index}
        for index, url in enumerate(payload.get("images", []))
    ]

    part = Part.model_validate(payload)
    settings = get_settings()
    title = build_title(part)
    item_specifics = build_item_specifics(part)
    description_html = build_description_html(part)
    xml_payload = build_listing_payload(part)
    category_id = get_category_id(part.part_category)
    condition_id = CONDITION_MAP.get(part.condition, DEFAULT_CONDITION_ID)
    price = part.price_aud * settings.price_margin_multiplier
    quantity = min(part.stock_qty, settings.listing_qty_cap)

    print("========================================")
    print("ZEParts Dry Run — Listing Builder")
    print("========================================")
    print(f"SKU:          {part.sku}")
    print(f"Title:        {title}   [{len(title)} chars]")
    print(f"Category ID:  {category_id}")
    print(f"Condition ID: {condition_id}")
    print(f"Price AUD:    ${price:.2f}")
    print(f"Quantity:     {quantity}")
    print(f"Images:       {len(part.images)}")
    print("Item Specifics:")
    for key, value in item_specifics.items():
        print(f"  {key}: {value}")
    print("----------------------------------------")
    print("Description HTML preview (first 300 chars):")
    print(f"{description_html[:300]}...")
    print("----------------------------------------")
    print("XML Payload (first 500 chars):")
    print(f"{xml_payload[:500]}...")
    print("========================================")
    print("✅ Dry run complete. No eBay API calls made.")


if __name__ == "__main__":
    asyncio.run(main())
