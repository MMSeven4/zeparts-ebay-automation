"""Unit tests for eBay listing payload construction."""

from __future__ import annotations

import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ["EBAY_CLIENT_ID"] = "client-id"
os.environ["EBAY_CLIENT_SECRET"] = "client-secret"
os.environ["EBAY_REFRESH_TOKEN"] = "refresh-token"
os.environ["CATALOG_API_BASE_URL"] = "https://catalog.example.com"
os.environ["CATALOG_API_KEY"] = "catalog-api-key"
os.environ["DB_URL"] = "postgresql+asyncpg://user:pass@localhost/db"

from src.catalog.models import Part
from src.core.config import get_settings
from src.ebay.listing_builder import (
    build_description_html,
    build_item_specifics,
    build_listing_payload,
    build_title,
)


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_parts.json"


def _load_first_part() -> Part:
    """Load the first sample part fixture and normalise images for the model."""

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
    payload["images"] = [
        {"url": url, "position": index}
        for index, url in enumerate(payload.get("images", []))
    ]
    return Part.model_validate(payload)


def test_build_title_normal() -> None:
    """Build a normal title containing the expected product metadata."""

    part = _load_first_part()

    title = build_title(part)

    assert part.brand in title
    assert part.part_name in title
    assert part.make in title
    assert part.model in title
    assert len(title) <= 80


def test_build_title_truncation() -> None:
    """Truncate long titles at a word boundary and keep them within 80 chars."""

    part = _load_first_part()
    part = part.model_copy(
        update={
            "part_name": (
                "Ultra Premium Heavy Duty Performance Ceramic Brake Pad Assembly "
                "For Touring Vehicles Across Australia"
            )
        }
    )

    full_title = (
        f"{part.brand} {part.part_name} suits {part.year_range} "
        f"{part.make} {part.model}"
    ).strip()
    title = build_title(part)

    assert len(title) <= 80
    if len(title) < len(full_title):
        assert full_title[len(title)] == " "


def test_build_item_specifics_keys() -> None:
    """Always include the required item specifics."""

    part = _load_first_part()

    specifics = build_item_specifics(part)

    assert "Brand" in specifics
    assert "Manufacturer Part Number" in specifics


def test_build_description_contains_sku() -> None:
    """Include the SKU in the rendered listing description."""

    part = _load_first_part()

    description = build_description_html(part)

    assert part.sku in description


def test_build_listing_payload_is_valid_xml() -> None:
    """Produce XML that can be parsed by ElementTree."""

    get_settings.cache_clear()
    part = _load_first_part()

    payload = build_listing_payload(part)
    root = ET.fromstring(payload)

    assert root.tag.endswith("AddItemRequest")


def test_build_listing_payload_contains_cdata() -> None:
    """Wrap the description HTML in a CDATA section."""

    get_settings.cache_clear()
    part = _load_first_part()

    payload = build_listing_payload(part)

    assert "<![CDATA[" in payload


def test_condition_mapping_new() -> None:
    """Map condition='new' to the correct eBay ConditionID."""

    get_settings.cache_clear()
    part = _load_first_part()
    part = part.model_copy(update={"condition": "new"})

    payload = build_listing_payload(part)

    assert "<ConditionID>1000</ConditionID>" in payload
