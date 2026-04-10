"""Create a real eBay sandbox listing from the sample catalog fixture."""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
os.environ.setdefault("DB_URL", "sqlite+aiosqlite:///./zeparts_dev.db")

from dotenv import load_dotenv

load_dotenv()

from src.catalog.models import Part
from src.core.config import get_settings
from src.core.logging import get_logger
from src.ebay.listing_builder import build_listing_payload, build_title
from src.ebay.trading_api import EbayTradingClient


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


async def main() -> None:
    """Load the sample fixture and create a live eBay sandbox listing."""

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
    title = build_title(part)

    print(f"Creating sandbox listing for: {part.sku} - {title}")
    if not settings.ebay_sandbox_mode:
        print("Warning: EBAY_SANDBOX_MODE is false. This script is intended for sandbox use.")

    xml_payload = await build_listing_payload(part)
    print("XML preview (first 300 chars):")
    print(xml_payload[:300])

    client = EbayTradingClient()

    try:
        item_id = await client.add_item_xml(xml_payload)
    except Exception as exc:
        _logger().exception(
            "Sandbox listing creation failed.",
            extra={"sku": part.sku},
        )
        print(f"Failed to create sandbox listing: {exc}")
        return

    print("✅ Listing created successfully!")
    print(f"eBay Item ID: {item_id}")
    print(f"View at: https://sandbox.ebay.com.au/itm/{item_id}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
