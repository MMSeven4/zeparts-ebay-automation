"""Secret access helpers backed by Google Secret Manager."""

from __future__ import annotations

import os

from google.api_core.exceptions import NotFound
from google.cloud import secretmanager

from src.core.logging import get_logger

_SECRET_CACHE: dict[tuple[str, str], str] = {}


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def get_secret(secret_id: str, project_id: str | None = None) -> str:
    """Fetch a secret value from Google Secret Manager with per-process caching."""

    resolved_project_id = project_id or os.getenv("PUBSUB_PROJECT", "")
    if not resolved_project_id:
        _logger().warning(
            "Secret lookup skipped because no project id is configured.",
            extra={"secret_id": secret_id},
        )
        return ""

    cache_key = (resolved_project_id, secret_id)
    if cache_key in _SECRET_CACHE:
        return _SECRET_CACHE[cache_key]

    client = secretmanager.SecretManagerServiceClient()
    secret_path = (
        f"projects/{resolved_project_id}/secrets/{secret_id}/versions/latest"
    )

    try:
        response = client.access_secret_version(request={"name": secret_path})
    except NotFound:
        _logger().warning(
            "Secret not found in Secret Manager.",
            extra={"project_id": resolved_project_id, "secret_id": secret_id},
        )
        return ""

    secret_value = response.payload.data.decode("utf-8")
    _SECRET_CACHE[cache_key] = secret_value
    return secret_value
