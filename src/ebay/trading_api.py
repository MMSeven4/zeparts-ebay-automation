"""Thin async wrapper for the XML-based eBay Trading API."""

from __future__ import annotations

from collections import defaultdict
import xml.etree.ElementTree as ET

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger
from src.ebay.auth import get_ebay_token


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


class EbayTradingClient:
    """Call selected eBay Trading API operations for AU listings."""

    SANDBOX_ENDPOINT = "https://api.sandbox.ebay.com/ws/api.dll"
    PRODUCTION_ENDPOINT = "https://api.ebay.com/ws/api.dll"
    SITE_ID = "15"
    COMPATIBILITY_LEVEL = "967"
    XML_NAMESPACE = "urn:ebay:apis:eBLBaseComponents"
    VALID_END_REASONS = {"NotAvailable", "Sold", "OtherListingError"}

    def __init__(self) -> None:
        """Initialise the client using application settings."""

        self._settings = get_settings()
        self._dev_id = get_settings().ebay_dev_id

    @property
    def endpoint(self) -> str:
        """Return the eBay Trading API endpoint for the active environment."""

        if self._settings.ebay_sandbox_mode:
            return self.SANDBOX_ENDPOINT
        return self.PRODUCTION_ENDPOINT

    async def _post(self, call_name: str, xml_body: str) -> dict:
        """Post an XML Trading API request and return a simplified response."""

        token = await get_ebay_token()
        headers = {
            "X-EBAY-API-CALL-NAME": call_name,
            "X-EBAY-API-SITEID": self.SITE_ID,
            "X-EBAY-API-COMPATIBILITY-LEVEL": self.COMPATIBILITY_LEVEL,
            "X-EBAY-API-APP-NAME": self._settings.ebay_client_id,
            "X-EBAY-API-DEV-NAME": self._dev_id,
            "X-EBAY-API-CERT-NAME": self._settings.ebay_client_secret,
            "Content-Type": "text/xml",
            "Authorization": f"Bearer {token}",
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self.endpoint,
                headers=headers,
                content=xml_body,
            )

        response.raise_for_status()

        root = ET.fromstring(response.text)
        self._raise_for_api_errors(root)
        return self._element_children_to_dict(root)

    async def add_item(self, payload: dict) -> str:
        """Create a new eBay listing and return the resulting item id."""

        xml = self._xml_add_item(payload)
        response = await self._post("AddItem", xml)
        item_id = str(response["ItemID"])

        _logger().info(
            "AddItem success",
            extra={"item_id": item_id, "sku": payload.get("sku")},
        )
        return item_id

    async def add_item_xml(self, xml: str) -> str:
        """Create a new eBay listing using a prebuilt XML payload."""

        response = await self._post("AddItem", xml)
        if "ItemID" not in response:
            print(response)
        item_id = str(response["ItemID"])

        _logger().info(
            "AddItem success",
            extra={"item_id": item_id},
        )
        return item_id

    async def revise_item(self, item_id: str, payload: dict) -> str:
        """Revise an existing eBay listing."""

        revise_payload = dict(payload)
        revise_payload["item_id"] = item_id
        xml = self._xml_add_item(revise_payload)
        await self._post("ReviseItem", xml)

        _logger().info(
            "ReviseItem success",
            extra={"item_id": item_id, "sku": payload.get("sku")},
        )
        return item_id

    async def end_item(self, item_id: str, reason: str = "NotAvailable") -> None:
        """End an existing eBay listing for a supported reason code."""

        if reason not in self.VALID_END_REASONS:
            raise ValueError(f"Invalid EndItem reason: {reason}")

        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<EndItemRequest xmlns="{self.XML_NAMESPACE}">'
            f"<ItemID>{item_id}</ItemID>"
            f"<EndingReason>{reason}</EndingReason>"
            "</EndItemRequest>"
        )
        await self._post("EndItem", xml)

        _logger().info("EndItem success", extra={"item_id": item_id})

    async def revise_inventory_status(
        self, item_id: str, quantity: int | None, price: float | None
    ) -> None:
        """Update listing quantity and/or price via ReviseInventoryStatus."""

        if quantity is None and price is None:
            raise ValueError(
                "At least one of quantity or price must be provided."
            )

        fields: list[str] = [f"<ItemID>{item_id}</ItemID>"]
        if quantity is not None:
            fields.append(f"<Quantity>{quantity}</Quantity>")
        if price is not None:
            fields.append(f"<StartPrice>{price}</StartPrice>")

        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<ReviseInventoryStatusRequest xmlns="{self.XML_NAMESPACE}">'
            "<InventoryStatus>"
            f"{''.join(fields)}"
            "</InventoryStatus>"
            "</ReviseInventoryStatusRequest>"
        )
        await self._post("ReviseInventoryStatus", xml)

        _logger().info(
            "ReviseInventoryStatus success",
            extra={"item_id": item_id},
        )

    def _xml_add_item(self, payload: dict) -> str:
        """Return a minimal placeholder XML request for AddItem-like calls."""

        sku = payload.get("sku", "")
        item_id = payload.get("item_id", "")
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<AddItemRequest xmlns="{self.XML_NAMESPACE}">'
            "<Item>"
            f"<SKU>{sku}</SKU>"
            f"<ItemID>{item_id}</ItemID>"
            "<!-- # TODO: implement full listing XML builder in listing_builder.py -->"
            "</Item>"
            "</AddItemRequest>"
        )

    def _raise_for_api_errors(self, root: ET.Element) -> None:
        """Raise a ValueError when the response includes a fatal API error."""

        for error in root.iter():
            if self._strip_namespace(error.tag) != "Errors":
                continue

            severity = self._find_child_text(error, "SeverityCode")
            if severity != "Error":
                continue

            message = self._find_child_text(error, "LongMessage") or (
                "eBay Trading API returned an error."
            )
            raise ValueError(message)

    def _element_children_to_dict(self, element: ET.Element) -> dict:
        """Convert an XML element's children into a simple nested dictionary."""

        result: dict[str, object] = {}
        grouped_children: dict[str, list[object]] = defaultdict(list)

        for child in element:
            child_tag = self._strip_namespace(child.tag)
            child_value = self._element_to_value(child)
            grouped_children[child_tag].append(child_value)

        for child_tag, values in grouped_children.items():
            result[child_tag] = values[0] if len(values) == 1 else values

        return result

    def _element_to_value(self, element: ET.Element) -> object:
        """Convert an XML element into text or a nested dictionary."""

        if list(element):
            return self._element_children_to_dict(element)
        return (element.text or "").strip()

    def _find_child_text(self, element: ET.Element, child_name: str) -> str | None:
        """Return the text for the first child element matching the given name."""

        for child in element:
            if self._strip_namespace(child.tag) == child_name:
                return (child.text or "").strip()
        return None

    def _strip_namespace(self, tag: str) -> str:
        """Remove an XML namespace prefix from an element tag."""

        return tag.split("}", maxsplit=1)[-1]
