"""Helpers for validating external images and uploading them to eBay."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger
from src.ebay.auth import get_ebay_token
from src.ebay.trading_api import EbayTradingClient

MAX_IMAGE_BYTES = 7 * 1024 * 1024
MIN_IMAGE_BYTES = 1024


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def _response_text(element: ET.Element, tag_name: str) -> str | None:
    """Return the text for the first XML element matching the given tag."""

    for child in element.iter():
        if child.tag.split("}", maxsplit=1)[-1] == tag_name:
            return (child.text or "").strip() or None
    return None


def _filename_from_url(source_url: str) -> str:
    """Derive a stable filename for eBay picture uploads from the source URL."""

    parsed = urlparse(source_url)
    filename = PurePosixPath(parsed.path).name
    if not filename:
        return "image.jpg"
    return unquote(filename)


async def fetch_and_validate_image(url: str) -> bytes | None:
    """Fetch an image URL and return valid image bytes or ``None`` on failure."""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
    except Exception as exc:
        _logger().warning(
            "Image fetch failed.",
            extra={"url": url, "reason": str(exc)},
        )
        return None

    if response.status_code != 200:
        _logger().warning(
            "Image validation failed.",
            extra={"url": url, "reason": f"http_status_{response.status_code}"},
        )
        return None

    content_type = response.headers.get("Content-Type", "")
    if not content_type.lower().startswith("image/"):
        _logger().warning(
            "Image validation failed.",
            extra={"url": url, "reason": f"invalid_content_type:{content_type}"},
        )
        return None

    image_bytes = response.content
    image_size = len(image_bytes)

    if image_size < MIN_IMAGE_BYTES:
        _logger().warning(
            "Image validation failed.",
            extra={"url": url, "reason": f"image_too_small:{image_size}"},
        )
        return None

    if image_size > MAX_IMAGE_BYTES:
        _logger().warning(
            "Image validation failed.",
            extra={"url": url, "reason": f"image_too_large:{image_size}"},
        )
        return None

    return image_bytes


async def upload_image_to_ebay(image_bytes: bytes, source_url: str) -> str | None:
    """Upload image bytes to eBay Picture Services and return the hosted URL."""

    settings = get_settings()
    client = EbayTradingClient()

    try:
        token = await get_ebay_token()
        filename = escape(_filename_from_url(source_url))
        xml_payload = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<UploadSiteHostedPicturesRequest xmlns="{client.XML_NAMESPACE}">'
            "<RequesterCredentials>"
            f"<eBayAuthToken>{escape(token)}</eBayAuthToken>"
            "</RequesterCredentials>"
            f"<PictureName>{filename}</PictureName>"
            "<PictureSet>Supersize</PictureSet>"
            "</UploadSiteHostedPicturesRequest>"
        )
        headers = {
            "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
            "X-EBAY-API-SITEID": client.SITE_ID,
            "X-EBAY-API-COMPATIBILITY-LEVEL": client.COMPATIBILITY_LEVEL,
            "X-EBAY-API-APP-NAME": settings.ebay_client_id,
            "X-EBAY-API-DEV-NAME": settings.ebay_dev_id,
            "X-EBAY-API-CERT-NAME": settings.ebay_client_secret,
            "Authorization": f"Bearer {token}",
        }

        async with httpx.AsyncClient(timeout=60) as http_client:
            response = await http_client.post(
                client.endpoint,
                headers=headers,
                data={"XML Payload": xml_payload},
                files={
                    "image": (
                        _filename_from_url(source_url),
                        image_bytes,
                        "image/jpeg",
                    )
                },
            )
    except Exception as exc:
        _logger().warning(
            "Image upload to eBay failed.",
            extra={"source_url": source_url, "reason": str(exc)},
        )
        return None

    if response.status_code != 200:
        _logger().warning(
            "Image upload to eBay failed.",
            extra={
                "source_url": source_url,
                "reason": f"http_status_{response.status_code}",
            },
        )
        return None

    try:
        response_text = response.text
        _logger().info(
            "eBay picture upload raw response",
            extra={"preview": response_text[:500]},
        )
        # eBay sometimes returns junk after the XML closing tag
        # Find the end of the XML document and truncate
        xml_end = response_text.rfind(">")
        if xml_end == -1:
            raise ValueError("No XML found in response")
        clean_xml = response_text[: xml_end + 1]
        root = ET.fromstring(clean_xml)
        client._raise_for_api_errors(root)
        full_url = _response_text(root, "FullURL")
    except Exception as exc:
        _logger().warning(
            "Image upload response parsing failed.",
            extra={"source_url": source_url, "reason": str(exc)},
        )
        return None

    if not full_url:
        _logger().warning(
            "Image upload to eBay failed.",
            extra={"source_url": source_url, "reason": "missing_full_url"},
        )
        return None

    return full_url
