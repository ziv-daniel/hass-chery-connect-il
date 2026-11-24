"""DataUpdateCoordinator for the Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import CheryApiError, CheryConnectApiClient, InvalidAuthError
from .const import API_TIME_ZONE, DOMAIN, LOCATION_OVERLAY_FIELDS

_LOGGER = logging.getLogger(__name__)

type CheryConfigEntry = ConfigEntry[CheryConnectCoordinator]


def _parse_gps_time(value: Any) -> datetime | None:
    """Parse a GPSDatetime string, else None; naive times are API-local."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_time_zone(API_TIME_ZONE))
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

    config_entry: CheryConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        api: CheryConnectApiClient,
        entry: CheryConfigEntry,
        update_interval: timedelta,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch fresh data from the API.

        Raises:
            ConfigEntryAuthFailed: When the token is rejected (HTTP 401).
            UpdateFailed: For any other API or network failure.

        """
        _LOGGER.debug(
            "Scheduled refresh started (every %s, entry %s)",
            self.update_interval,
            self.config_entry.title,
        )
        try:
            vehicle = await self.api.get_vehicle_info()
            location = await self.api.get_last_location()
        except InvalidAuthError as err:
            _LOGGER.debug("Refresh: token rejected, starting re-authentication")
            raise ConfigEntryAuthFailed("Chery Connect token rejected") from err
        except CheryApiError as err:
            _LOGGER.debug("Refresh failed: %s", err)
            raise UpdateFailed(f"Failed to fetch Chery data: {err}") from err

        merged: dict[str, Any] = dict(vehicle)
        use_location = _is_newer(
            location.get("GPSDatetime"), vehicle.get("GPSDatetime")
        )
        _LOGGER.debug(
            "Refresh done: position from %s (GPS time VehicleInfo=%s, lastLocation=%s)",
            "lastLocation" if use_location else "VehicleInfo",
            vehicle.get("GPSDatetime"),
            location.get("GPSDatetime"),
        )
        if use_location:
            for field in LOCATION_OVERLAY_FIELDS:
                if field in location:
                    merged[field] = location[field]
            if location.get("GPSDatetime") is not None:
                merged["GPSDatetime"] = location["GPSDatetime"]
        return merged
