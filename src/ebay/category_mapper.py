"""Category mapping helpers for eBay AU Motors parts listings."""

from __future__ import annotations

from src.core.logging import get_logger

CATEGORY_MAP: dict[str, int] = {
    "Alternators": 36285,
    "Starters": 36288,
    "Brake Pads": 33560,
    "Brake Rotors": 33558,
    "Brake Calipers": 33556,
    "Shock Absorbers": 33616,
    "Struts": 33618,
    "Control Arms": 33606,
    "Ball Joints": 33600,
    "Tie Rod Ends": 33638,
    "Wheel Bearings": 33642,
    "CV Joints": 33604,
    "Radiators": 33592,
    "Thermostats": 33596,
    "Water Pumps": 33598,
    "Fuel Pumps": 33574,
    "Fuel Injectors": 33572,
    "Air Filters": 33548,
    "Oil Filters": 33582,
    "Timing Belts": 33632,
    "Timing Chains": 33634,
    "Serpentine Belts": 33628,
    "Ignition Coils": 33578,
    "Spark Plugs": 33588,
    "Oxygen Sensors": 33584,
    "Mass Air Flow Sensors": 33580,
    "Throttle Bodies": 33594,
    "EGR Valves": 33568,
    "Catalytic Converters": 33562,
    "Exhaust Manifolds": 33566,
    "Clutch Kits": 33610,
    "Flywheels": 33612,
    "Transmission Filters": 33640,
    "Power Steering Pumps": 33590,
    "Headlights": 33644,
    "Tail Lights": 33648,
    "Window Regulators": 33652,
    "Wiper Motors": 33654,
}

DEFAULT_CATEGORY_ID = 6030


def _logger():
    """Return the module logger lazily to avoid early settings evaluation."""

    return get_logger(__name__)


def _normalise(value: str) -> str:
    """Normalise a category string for comparison."""

    return value.strip().casefold()


def get_category_id(part_category: str) -> int:
    """Resolve an internal category name to an eBay AU category id."""

    search_term = _normalise(part_category)
    if not search_term:
        _logger().warning(
            "Unknown eBay category mapping; using fallback.",
            extra={"part_category": part_category},
        )
        return DEFAULT_CATEGORY_ID

    for category_name, category_id in CATEGORY_MAP.items():
        if _normalise(category_name) == search_term:
            return category_id

    for category_name, category_id in CATEGORY_MAP.items():
        normalised_name = _normalise(category_name)
        if normalised_name in search_term or search_term in normalised_name:
            return category_id

    _logger().warning(
        "Unknown eBay category mapping; using fallback.",
        extra={"part_category": part_category},
    )
    return DEFAULT_CATEGORY_ID


def get_category_name(category_id: int) -> str | None:
    """Return the category name for a known eBay AU category id."""

    for category_name, mapped_id in CATEGORY_MAP.items():
        if mapped_id == category_id:
            return category_name
    return None
