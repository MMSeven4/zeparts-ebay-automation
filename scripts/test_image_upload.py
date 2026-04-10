"""Create a sandbox listing that references a direct public image URL."""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///./zeparts_dev.db")

from dotenv import load_dotenv

load_dotenv()

from src.catalog.models import Part, PartImage
from src.core.config import get_settings
from src.ebay.listing_builder import build_listing_payload, build_title
from src.ebay.trading_api import EbayTradingClient

TEST_IMAGE_URL = "https://media.zepro.pro/media/DTSPAREPARTS/01312900-custom1.jpg"


async def main() -> None:
    """Create a sandbox listing that uses a direct public image URL."""

    settings = get_settings()
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
    part.images = [PartImage(url=TEST_IMAGE_URL, position=0)]
    title = build_title(part)

    print(f"Creating sandbox listing with direct image URL for: {part.sku} - {title}")
    if not settings.ebay_sandbox_mode:
        print("Warning: EBAY_SANDBOX_MODE is false. This script is intended for sandbox use.")

    xml_payload = await build_listing_payload(part)
    image_url_in_xml = TEST_IMAGE_URL in xml_payload
    print(f"Image URL present in XML: {'yes' if image_url_in_xml else 'no'}")

    client = EbayTradingClient()

    try:
        item_id = await client.add_item_xml(xml_payload)
    except Exception as exc:
        print(f"Failed to create sandbox listing: {exc}")
        return

    print(f"New eBay Item ID: {item_id}")
    print(f"Direct image URL used: {TEST_IMAGE_URL}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
