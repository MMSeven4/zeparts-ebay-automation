"""Application configuration models and loaders."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    ebay_client_id: str
    ebay_dev_id: str
    ebay_client_secret: str
    ebay_refresh_token: str
    ebay_sandbox_mode: bool = False

    catalog_api_base_url: str
    catalog_api_key: str

    db_url: str

    gcs_bucket_image_staging: str = "zeparts-image-staging"
    pubsub_project: str = "zeparts-au"
    pubsub_listing_topic: str = "listing-jobs"
    pubsub_sync_topic: str = "sync-jobs"
    pubsub_image_topic: str = "image-jobs"

    listing_qty_cap: int = 99
    price_margin_multiplier: float = 1.0
    dry_run: bool = False

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings instance."""

    return Settings()
