"""Diagnostics for the Chery Connect integration.

Users attach this to bug reports instead of raw logs, so everything that
identifies the owner, the car or its location is redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_IPOINTER_REFRESH_TOKEN,
    CONF_IPOINTER_TOKEN,
    CONF_MOBILE_PHONE,
    CONF_TOKEN,
    CONF_V_NUMBER,
)
from .coordinator import CheryConfigEntry

TO_REDACT_ENTRY = {
    CONF_TOKEN,
    CONF_IPOINTER_TOKEN,
    CONF_IPOINTER_REFRESH_TOKEN,
    CONF_MOBILE_PHONE,
    CONF_V_NUMBER,
    "unique_id",
    "title",
}
TO_REDACT_DATA = {"Vnumber", "VIN", "Vin", "Latitude", "Longtitude", "Address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CheryConfigEntry
) -> dict[str, Any]:
    """Return redacted entry and vehicle data."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT_ENTRY),
        "last_update_success": coordinator.last_update_success,
        "ev_login": coordinator.ev_login,
        "data": async_redact_data(coordinator.data or {}, TO_REDACT_DATA),
    }
