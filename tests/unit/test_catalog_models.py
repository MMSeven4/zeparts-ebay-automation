"""Unit tests for catalog models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.catalog.models import CatalogPage, FitmentEntry, Part


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "sample_parts.json"


def _load_sample_parts() -> list[dict]:
    """Load the sample catalog parts fixture and normalise image objects."""

    raw_parts = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for part in raw_parts:
        part["images"] = [
            {"url": url, "position": index}
            for index, url in enumerate(part.get("images", []))
        ]
    return raw_parts


def test_part_valid() -> None:
    """Create a valid part from the sample fixture."""

    sample_part = _load_sample_parts()[0]
    part = Part.model_validate(sample_part)

    assert part.sku == "ZE-BRK-001"
    assert part.brand == "Bendix"
    assert part.price_aud == 129.95


def test_part_invalid_condition() -> None:
    """Reject unsupported part conditions."""

    sample_part = _load_sample_parts()[0]
    sample_part["condition"] = "broken"

    with pytest.raises(ValidationError):
        Part.model_validate(sample_part)


def test_part_empty_sku() -> None:
    """Reject empty part SKUs."""

    sample_part = _load_sample_parts()[0]
    sample_part["sku"] = "   "

    with pytest.raises(ValidationError):
        Part.model_validate(sample_part)


def test_fitment_entry_valid() -> None:
    """Create a valid fitment entry."""

    entry = FitmentEntry(year=2018, make="Toyota", model="Camry")

    assert entry.year == 2018
    assert entry.make == "Toyota"
    assert entry.model == "Camry"


def test_catalog_page_has_next_true() -> None:
    """Set has_next=True when additional pages remain."""

    page = CatalogPage(
        parts=[],
        total_count=25,
        page=1,
        page_size=10,
        has_next=True,
    )

    assert page.has_next is True
