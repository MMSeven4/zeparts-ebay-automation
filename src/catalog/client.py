"""Authenticated client for the private B2B catalog API."""

# INTEGRATION NOTE: This client assumes a REST JSON catalog API.
# Update BASE_PATH, endpoint paths, and field mappings in _parse_part()
# once the real catalog API contract is confirmed.

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from src.catalog.models import CatalogPage, FitmentEntry, Part, PartImage
from src.core.config import get_settings
from src.core.logging import get_logger


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


class CatalogClient:
    """Async HTTP client for the private ZEParts catalog service."""

    BASE_PATH = ""

    def __init__(self) -> None:
        """Initialise the client using environment-backed settings."""

        self._settings = get_settings()
        self._base_url = self._settings.catalog_api_base_url.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        """Return the authenticated headers for catalog API requests."""

        return {
            "Authorization": f"Bearer {self._settings.catalog_api_key}",
            "Accept": "application/json",
            "User-Agent": "ZEParts-Automation/1.0",
        }

    async def get_part(self, sku: str) -> Part | None:
        """Fetch a single part by SKU."""

        url = f"{self._base_url}{self.BASE_PATH}/parts/{sku}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return self._parse_part(response.json())

    async def get_page(self, page: int = 1, page_size: int = 100) -> CatalogPage:
        """Fetch a paginated part result set from the catalog."""

        url = f"{self._base_url}{self.BASE_PATH}/parts"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                headers=self._headers,
                params={"page": page, "page_size": page_size},
            )

        response.raise_for_status()
        return self._parse_catalog_page(response.json())

    async def get_all_skus(self) -> list[str]:
        """Fetch all known SKUs from the catalog, with pagination fallback."""

        url = f"{self._base_url}{self.BASE_PATH}/parts/skus"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code != 404:
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                raw_skus = payload.get("skus", [])
            else:
                raw_skus = payload
            skus = [str(sku).strip() for sku in raw_skus if str(sku).strip()]
            _logger().info("Fetched N skus from catalog", extra={"count": len(skus)})
            return skus

        skus: list[str] = []
        page_number = 1
        while True:
            page = await self.get_page(page=page_number)
            skus.extend(part.sku for part in page.parts)
            if not page.has_next:
                break
            page_number += 1

        _logger().info("Fetched N skus from catalog", extra={"count": len(skus)})
        return skus

    async def check_availability(self, sku: str) -> bool:
        """Check whether a given SKU is currently available in the catalog."""

        url = f"{self._base_url}{self.BASE_PATH}/parts/{sku}/availability"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers)

        if response.status_code == 404:
            return False

        response.raise_for_status()
        data = response.json()
        return bool(data.get("available", False))

    def _parse_part(self, data: dict[str, Any]) -> Part:
        """Map a raw catalog payload into the canonical Part model."""

        raw_images = data.get("images", [])
        images = [
            PartImage(
                url=image.get("url"),
                position=image.get("sort_order", image.get("position", 0)),
                alt_text=image.get("alt_text"),
            )
            for image in raw_images
            if isinstance(image, dict) and isinstance(image.get("url"), str) and image.get("url")
        ]

        raw_fitment = data.get("fitment", [])
        fitment = [
            FitmentEntry(
                year=entry["year"],
                make=entry["make"],
                model=entry["model"],
                submodel=entry.get("submodel"),
                engine=entry.get("engine"),
                trim=entry.get("trim"),
            )
            for entry in raw_fitment
            if isinstance(entry, dict)
        ]

        def first_non_none(*values: Any) -> Any:
            """Return the first value that is not None."""

            for value in values:
                if value is not None:
                    return value
            return None

        mapped_data = {
            "sku": first_non_none(data.get("sku"), data.get("part_number"), data.get("id")),
            "brand": data.get("brand"),
            "part_name": first_non_none(data.get("part_name"), data.get("name")),
            "part_category": first_non_none(
                data.get("part_category"),
                data.get("category"),
            ),
            "year_range": first_non_none(
                data.get("year_range"),
                data.get("display_year_range"),
            ),
            "make": data.get("make"),
            "model": data.get("model"),
            "submodel": data.get("submodel"),
            "condition": data.get("condition", "new"),
            "price_aud": first_non_none(data.get("price_aud"), data.get("price")),
            "stock_qty": first_non_none(
                data.get("stock_qty"),
                data.get("quantity_on_hand"),
                0,
            ),
            "available": data.get("available", True),
            "oem_number": data.get("oem_number"),
            "interchange_numbers": data.get("interchange_numbers", []),
            "fitment": fitment,
            "images": images,
            "description": data.get("description"),
            "weight_kg": data.get("weight_kg"),
            "length_cm": data.get("length_cm"),
            "width_cm": data.get("width_cm"),
            "height_cm": data.get("height_cm"),
        }

        try:
            return Part.model_validate(mapped_data)
        except ValidationError:
            _logger().warning(
                "Failed to parse catalog part payload.",
                extra={"sku": mapped_data.get("sku")},
            )
            raise

    def _parse_catalog_page(self, data: dict[str, Any]) -> CatalogPage:
        """Parse a paginated catalog response into the canonical page model."""

        items = data.get("items")
        if items is None:
            items = data.get("parts", [])

        page = int(data.get("page", 1))
        page_size = int(data.get("page_size", len(items)))
        total = int(data.get("total", len(items)))
        has_next = (page * page_size) < total

        return CatalogPage(
            parts=[self._parse_part(item) for item in items],
            total_count=total,
            page=page,
            page_size=page_size,
            has_next=has_next,
        )
