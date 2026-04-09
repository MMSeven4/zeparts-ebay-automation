"""Pydantic models for catalog entities and pagination envelopes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictBaseModel(BaseModel):
    """Base model configured for strict validation."""

    model_config = ConfigDict(strict=True)


class FitmentEntry(StrictBaseModel):
    """Vehicle fitment information for a catalog part."""

    year: int
    make: str
    model: str
    submodel: str | None = None
    engine: str | None = None
    trim: str | None = None


class PartImage(StrictBaseModel):
    """Image metadata for a catalog part."""

    url: str
    position: int = 0
    alt_text: str | None = None


class Part(StrictBaseModel):
    """Canonical catalog part model used across ingestion and listing flows."""

    sku: str
    brand: str
    part_name: str
    part_category: str
    year_range: str
    make: str
    model: str
    submodel: str | None = None
    condition: str = "new"
    price_aud: float
    stock_qty: int
    available: bool = True
    oem_number: str | None = None
    interchange_numbers: list[str] = Field(default_factory=list)
    fitment: list[FitmentEntry] = Field(default_factory=list)
    images: list[PartImage] = Field(default_factory=list)
    description: str | None = None
    weight_kg: float | None = None
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, v: str) -> str:
        """Normalise and validate the supported part condition values."""

        allowed = {"new", "used", "remanufactured"}
        normalised = v.lower()
        if normalised not in allowed:
            raise ValueError(f"condition must be one of {allowed}")
        return normalised

    @field_validator("sku")
    @classmethod
    def validate_sku(cls, v: str) -> str:
        """Ensure the part SKU is present and not blank."""

        stripped_value = v.strip()
        if not stripped_value:
            raise ValueError("sku cannot be empty")
        return stripped_value


class CatalogPage(StrictBaseModel):
    """Pagination wrapper for catalog part results."""

    parts: list[Part]
    total_count: int
    page: int
    page_size: int
    has_next: bool
