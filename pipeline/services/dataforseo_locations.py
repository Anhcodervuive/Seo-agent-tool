"""Validated Google country locations supported by DataForSEO.

The checked-in catalogue is generated from DataForSEO's Google SERP locations
CSV.  We intentionally expose country-level locations in the product: they
cover the common ranking/search-volume use case, remain searchable in a normal
select control, and avoid presenting the provider's very large city/postcode
catalogue as an unusable dropdown.
"""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_GOOGLE_LOCATION = "United States"
MAX_COMPETITOR_TRAFFIC_MARKETS = 10
_CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "dataforseo_google_country_locations.json"


def _load_locations():
    with _CATALOGUE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


GOOGLE_LOCATIONS = tuple(_load_locations())
GOOGLE_LOCATION_BY_CASEFOLD = {
    location["name"].casefold(): location
    for location in GOOGLE_LOCATIONS
}


def normalize_google_location(raw_location: str | None) -> str:
    """Return the exact provider name or raise a helpful validation error."""
    value = (raw_location or DEFAULT_GOOGLE_LOCATION).strip()
    match = GOOGLE_LOCATION_BY_CASEFOLD.get(value.casefold())
    if match:
        return match["name"]
    raise ValueError(
        f"Unsupported DataForSEO Google location '{value}'. "
        "Choose a country from the location dropdown."
    )


def google_location_names() -> tuple[str, ...]:
    return tuple(location["name"] for location in GOOGLE_LOCATIONS)


def normalize_competitor_traffic_locations(raw_locations, primary_location: str | None) -> list[str]:
    """Return unique supported markets, always beginning with project location."""
    primary = normalize_google_location(primary_location)
    values = raw_locations if isinstance(raw_locations, (list, tuple)) else []
    normalized = [primary]
    for raw_location in values:
        location = normalize_google_location(raw_location)
        if location not in normalized:
            normalized.append(location)
    if len(normalized) > MAX_COMPETITOR_TRAFFIC_MARKETS:
        raise ValueError(
            f"Choose at most {MAX_COMPETITOR_TRAFFIC_MARKETS} competitor traffic markets, including the primary target location."
        )
    return normalized
