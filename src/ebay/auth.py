"""OAuth token management for eBay user-authenticated API access."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


class EbayTokenManager:
    """Manage cached eBay OAuth user tokens with proactive refresh."""

    SANDBOX_TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    PRODUCTION_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    SCOPES = [
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
        "https://api.ebay.com/oauth/api_scope/sell.account",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    ]

    def __init__(self) -> None:
        """Initialise the token cache state and concurrency lock."""

        self._token: str | None = None
        self._expires_at: datetime = datetime.min
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a cached token or refresh it when it is near expiry."""

        async with self._lock:
            now = datetime.utcnow()
            if (
                self._token is not None
                and self._expires_at - now > timedelta(minutes=5)
            ):
                return self._token

            return await self._refresh()

    async def _refresh(self) -> str:
        """Refresh the eBay user token using the refresh token grant."""

        settings = get_settings()
        token_url = (
            self.SANDBOX_TOKEN_URL
            if settings.ebay_sandbox_mode
            else self.PRODUCTION_TOKEN_URL
        )

        credentials = (
            f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode(
                "utf-8"
            )
        )
        encoded_credentials = base64.b64encode(credentials).decode("ascii")
        headers = {
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        form_data = {
            "grant_type": "refresh_token",
            "refresh_token": settings.ebay_refresh_token,
            "scope": " ".join(self.SCOPES),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                token_url,
                headers=headers,
                data=form_data,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            _logger().error(
                "eBay token refresh failed.",
                extra={
                    "status_code": response.status_code,
                    "sandbox": settings.ebay_sandbox_mode,
                },
            )
            raise

        payload = response.json()
        access_token = payload["access_token"]
        expires_in = int(payload["expires_in"])

        self._token = access_token
        self._expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        _logger().info(
            "eBay token refreshed",
            extra={
                "sandbox": settings.ebay_sandbox_mode,
                "expires_in": expires_in,
            },
        )

        return access_token


token_manager = EbayTokenManager()


async def get_ebay_token() -> str:
    """Return the active eBay OAuth token."""

    return await token_manager.get_token()
