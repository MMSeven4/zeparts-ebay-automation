"""Build complete eBay AddItem XML payloads from catalog parts."""

from __future__ import annotations

import re
from html import escape
import xml.etree.ElementTree as ET

from src.catalog.models import Part
from src.core.config import get_settings
from src.core.logging import get_logger
from src.ebay.category_mapper import get_category_id

CONDITION_MAP: dict[str, int] = {
    "new": 1000,
    "used": 3000,
    "remanufactured": 2500,
    "reconditioned": 2500,
    "open box": 1500,
}
DEFAULT_CONDITION_ID = 1000

POSTAGE_POLICY_ID = "ZEParts_Standard_AU"
PAYMENT_POLICY_ID = "ZEParts_Payment_AU"
RETURN_POLICY_ID = "ZEParts_Returns_AU"

_DESCRIPTION_PLACEHOLDER = "__ZE_PARTS_DESCRIPTION__"


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def _clean_text(value: str | None) -> str:
    """Collapse whitespace and return a stripped text value."""

    if value is None:
        return ""
    return " ".join(value.split()).strip()


def _sanitise_description_html(value: str) -> str:
    """Remove unsafe script content and javascript href values."""

    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", value)
    cleaned = re.sub(
        r'(?i)href\s*=\s*(["\'])\s*javascript:[^"\']*\1',
        'href="#"',
        cleaned,
    )
    cleaned = re.sub(r"(?i)href\s*=\s*javascript:[^\s>]+", 'href="#"', cleaned)
    return cleaned.strip()


def build_title(part: Part) -> str:
    """Build a concise eBay listing title capped at 80 characters."""

    try:
        components = [
            _clean_text(part.brand),
            _clean_text(part.part_name),
            "suits",
            _clean_text(part.year_range),
            _clean_text(part.make),
            _clean_text(part.model),
        ]
        if part.submodel:
            components.append(_clean_text(part.submodel))

        title = " ".join(component for component in components if component).strip()
        if len(title) <= 80:
            return title.strip()

        truncated = title[:80]
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]
        return truncated.strip()
    except Exception:
        _logger().exception(
            "Failed to build listing title.",
            extra={"sku": getattr(part, "sku", None)},
        )
        return _clean_text(
            f"{getattr(part, 'brand', '')} {getattr(part, 'part_name', '')}"
        )[:80].strip()


def build_item_specifics(part: Part) -> dict[str, str]:
    """Build the eBay item specifics dictionary for the listing."""

    specifics = {
        "Brand": part.brand,
        "Manufacturer Part Number": part.oem_number or "OEM",
        "Condition": part.condition.title(),
        "Placement on Vehicle": "Universal",
        "Country/Region of Manufacture": "Australia",
    }

    if part.interchange_numbers:
        specifics["Interchange Part Number"] = ", ".join(part.interchange_numbers)

    return specifics


def build_description_html(part: Part) -> str:
    """Build a safe HTML description for the eBay listing."""

    description = part.description or "Quality automotive part from ZEParts Australia."
    description_html = _sanitise_description_html(description)

    detail_rows = [
        ("SKU", part.sku),
        ("Brand", part.brand),
        ("Condition", part.condition.title()),
        ("Part Category", part.part_category),
    ]
    if part.oem_number:
        detail_rows.insert(3, ("OEM Number", part.oem_number))

    rows_html = "".join(
        "<tr>"
        f"<td><strong>{escape(label)}</strong></td>"
        f"<td>{escape(value)}</td>"
        "</tr>"
        for label, value in detail_rows
    )

    if part.fitment:
        fitment_items = "".join(
            "<li>"
            f"{escape(' '.join(filter(None, [str(entry.year), entry.make, entry.model, entry.submodel or ''])))}"
            "</li>"
            for entry in part.fitment
        )
        fitment_html = f"<ul>{fitment_items}</ul>"
    else:
        fitment_html = (
            "<p>Please verify fitment with your vehicle's specifications before "
            "purchasing.</p>"
        )

    return (
        '<div style="font-family: Arial, sans-serif; max-width: 800px;">'
        f"<h2>{escape(_clean_text(f'{part.brand} {part.part_name}'))}</h2>"
        f"<p>{description_html}</p>"
        "<h3>Part Details</h3>"
        '<table style="border-collapse: collapse; width: 100%;">'
        f"{rows_html}"
        "</table>"
        "<h3>Fitment</h3>"
        f"{fitment_html}"
        "<hr/>"
        '<p style="font-size:11px;">'
        "ZEParts Australia Pty Ltd | ABN: [ABN PLACEHOLDER] | "
        "All parts are warranted against manufacturing defects."
        "</p>"
        "</div>"
    )


async def build_listing_payload(part: Part) -> str:
    """Build the complete eBay Trading API AddItem XML payload."""

    from src.ebay.auth import token_manager
    import asyncio

    _ = asyncio
    settings = get_settings()
    token = await token_manager.get_token()
    title = build_title(part)
    description_html = build_description_html(part).replace(
        "]]>",
        "]]]]><![CDATA[>",
    )
    condition_key = _clean_text(part.condition).lower()
    condition_id = CONDITION_MAP.get(condition_key, DEFAULT_CONDITION_ID)
    quantity = max(0, min(part.stock_qty, settings.listing_qty_cap))
    price = max(part.price_aud * settings.price_margin_multiplier, 0.0)

    root = ET.Element("AddItemRequest", xmlns="urn:ebay:apis:eBLBaseComponents")
    requester_credentials = ET.SubElement(root, "RequesterCredentials")
    ET.SubElement(requester_credentials, "eBayAuthToken").text = token
    item = ET.SubElement(root, "Item")

    ET.SubElement(item, "Title").text = title
    ET.SubElement(item, "Description").text = _DESCRIPTION_PLACEHOLDER

    primary_category = ET.SubElement(item, "PrimaryCategory")
    ET.SubElement(primary_category, "CategoryID").text = str(
        get_category_id(part.part_category)
    )

    ET.SubElement(item, "StartPrice").text = f"{price:.2f}"
    ET.SubElement(item, "ConditionID").text = str(condition_id)
    ET.SubElement(item, "Quantity").text = str(quantity)
    ET.SubElement(item, "SKU").text = part.sku
    ET.SubElement(item, "Country").text = "AU"
    ET.SubElement(item, "Currency").text = "AUD"
    ET.SubElement(item, "ListingType").text = "FixedPriceItem"
    ET.SubElement(item, "ListingDuration").text = "GTC"
    ET.SubElement(item, "DispatchTimeMax").text = "3"
    ET.SubElement(item, "Location").text = "Sydney, NSW"
    ET.SubElement(item, "PostalCode").text = "2000"

    item_specifics = ET.SubElement(item, "ItemSpecifics")
    for name, value in build_item_specifics(part).items():
        name_value_list = ET.SubElement(item_specifics, "NameValueList")
        ET.SubElement(name_value_list, "Name").text = name
        ET.SubElement(name_value_list, "Value").text = value

    picture_details = ET.SubElement(item, "PictureDetails")
    for image in sorted(part.images, key=lambda image: image.position)[:12]:
        ET.SubElement(picture_details, "PictureURL").text = image.url

    shipping_details = ET.SubElement(item, "ShippingDetails")
    shipping_service_options = ET.SubElement(
        shipping_details,
        "ShippingServiceOptions",
    )
    ET.SubElement(shipping_service_options, "ShippingServicePriority").text = "1"
    ET.SubElement(shipping_service_options, "ShippingService").text = "AU_Regular"
    ET.SubElement(shipping_service_options, "ShippingServiceCost").text = "9.95"

    return_policy = ET.SubElement(item, "ReturnPolicy")
    ET.SubElement(return_policy, "ReturnsAcceptedOption").text = "ReturnsAccepted"
    ET.SubElement(return_policy, "RefundOption").text = "MoneyBack"
    ET.SubElement(return_policy, "ReturnsWithinOption").text = "Days_30"
    ET.SubElement(return_policy, "ShippingCostPaidByOption").text = "Buyer"

    ET.SubElement(item, "PaymentMethods").text = "PayPal"
    ET.SubElement(item, "PayPalEmailAddress").text = "sandbox-zeparts@example.com"

    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    xml_body = xml_body.replace(
        f"<Description>{_DESCRIPTION_PLACEHOLDER}</Description>",
        f"<Description><![CDATA[{description_html}]]></Description>",
    )

    return '<?xml version="1.0" encoding="utf-8"?>' + xml_body
