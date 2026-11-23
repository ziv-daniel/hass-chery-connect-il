"""DataUpdateCoordinator for the Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CheryApiError, CheryConnectApiClient, InvalidAuthError
from .const import DOMAIN, LOCATION_OVERLAY_FIELDS

_LOGGER = logging.getLogger(__name__)


def _parse_gps_time(value: Any) -> datetime | None:
    """Parse a GPSDatetime string, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _is_newer(new_value: Any, old_value: Any) -> bool:
    """Return True when the new GPS time is newer than the old one.

    Mirrors the app's checkTimeDiff: any location reading counts when
    there is no previous one, and otherwise only a strictly newer
    GPSDatetime is applied.
    """
    if new_value is None:
        return False
    if old_value is None:
        return True
    new_time = _parse_gps_time(new_value)
    old_time = _parse_gps_time(old_value)
    if new_time is not None and old_time is not None:
        return new_time > old_time
    return str(new_value) > str(old_value)


class CheryConnectCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch VehicleInfo + lastLocation on an interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: CheryConnectApiClient,
        entry: ConfigEntry,
        update_interval,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch fresh data from the API.

        Raises:
            ConfigEntryAuthFailed: When the token is rejected (HTTP 401).
            UpdateFailed: For any other API or network failure.

        """
        try:
            vehicle = await self.api.get_vehicle_info()
            location = await self.api.get_last_location()
        except InvalidAuthError as err:
            raise ConfigEntryAuthFailed("Chery Connect token rejected") from err
        except (CheryApiError, aiohttp.ClientError) as err:
            raise UpdateFailed(f"Failed to fetch Chery data: {err}") from err

        merged: dict[str, Any] = dict(vehicle)
        if _is_newer(location.get("GPSDatetime"), vehicle.get("GPSDatetime")):
            for field in LOCATION_OVERLAY_FIELDS:
                if field in location:
                    merged[field] = location[field]
            if location.get("GPSDatetime") is not None:
                merged["GPSDatetime"] = location["GPSDatetime"]
        return merged
