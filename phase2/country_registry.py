"""Conservative manufacturer-home-country registry.

This is NOT a Made-In database. It records the country associated with the
manufacturer/brand identity, only after exact Part Number identity is proven.
Unknown manufacturers intentionally return None rather than being guessed.
"""
from __future__ import annotations

from typing import Optional, Tuple

from .resolver_v43 import canonical_manufacturer

MANUFACTURER_COUNTRY = {
    "microchip": "United States",
    "toshiba": "Japan",
    "infineon": "Germany",
    "renesas": "Japan",
    "onsemi": "United States",
    "fairchild": "United States",
    "ti": "United States",
    "nxp": "Netherlands",
    "analog_devices": "United States",
    "mitsubishi": "Japan",
    "fuji": "Japan",
    "sanken": "Japan",
    "allegro": "United States",
    "international_rectifier": "United States",
    "power_integrations": "United States",
    "rohm": "Japan",
    "panasonic": "Japan",
    "siemens": "Germany",
    "telefunken": "Germany",
    "teledyne": "United States",
    "thomson": "France",
    "signetics": "United States",
    "nec": "Japan",
    "sanyo": "Japan",
    "motorola": "United States",
    "national_semiconductor": "United States",
}


def resolve_manufacturer_country(manufacturer: str) -> Tuple[Optional[str], str]:
    if not manufacturer or not manufacturer.strip():
        return None, "NOT_RESOLVED_NO_MANUFACTURER"
    key = canonical_manufacturer(manufacturer)
    country = MANUFACTURER_COUNTRY.get(key)
    if country:
        return country, "RESOLVED_REGISTRY"
    return None, "NOT_RESOLVED"
