"""Device tracker for the Chery Connect integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker.const import SourceType
from homeassistant.components.device_tracker.entity import TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import parse_float
from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity

# The coordinator does all fetching; entities never poll on their own.
PARALLEL_UPDATES = 0


class CheryConnectDeviceTracker(CheryConnectEntity, TrackerEntity):
    """Vehicle location from lastLocation.

    Note the API's own typo: the longitude field is ``Longtitude``.
    """

    _attr_translation_key = "location"

    def __init__(self, coordinator: CheryConnectCoordinator) -> None:
        """Initialize the tracker."""
        super().__init__(coordinator, "tracker")

    @property
    def latitude(self) -> float | None:
        """Return the vehicle latitude."""
        return parse_float((self.coordinator.data or {}).get("Latitude"))

    @property
    def longitude(self) -> float | None:
        """Return the vehicle longitude."""
        return parse_float((self.coordinator.data or {}).get("Longtitude"))

    @property
    def source_type(self) -> SourceType:
        """Return the source type."""
        return SourceType.GPS

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return address, GPS time, speed and direction."""
        data = self.coordinator.data or {}
        return {
            "address": data.get("Address"),
            "gps_datetime": data.get("GPSDatetime"),
            "speed": parse_float(data.get("Speed")),
            "direction": data.get("Direction"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Chery Connect device tracker from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([CheryConnectDeviceTracker(coordinator)])
