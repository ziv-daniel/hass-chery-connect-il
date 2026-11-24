"""DataUpdateCoordinator for the Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CheryApiError, CheryConnectApiClient, InvalidAuthError, parse_api_time
from .const import (
    ACTIVE_SCAN_INTERVAL,
    CHARGING_ON_VALUES,
    DOMAIN,
    ENGINE_ON_VALUES,
    EVENT_DRIVER_ALERT,
    LOCATION_OVERLAY_FIELDS,
)
from .extras import CheryExtras, DriverAlert

_LOGGER = logging.getLogger(__name__)

type CheryConfigEntry = ConfigEntry[CheryConnectCoordinator]


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
    new_time = parse_api_time(new_value)
    old_time = parse_api_time(old_value)
    if new_time is not None and old_time is not None:
        return new_time > old_time
    return str(new_value) > str(old_value)


def is_active(data: dict[str, Any]) -> bool:
    """Return True while the engine runs or the car charges."""
    return (
        str(data.get("EngineOn")) in ENGINE_ON_VALUES
        or str(data.get("ElectricChargeStatus")) in CHARGING_ON_VALUES
    )


def merge_location(
    vehicle: dict[str, Any], location: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Overlay the newer lastLocation fields on VehicleInfo.

    Returns the merged data and whether lastLocation was used.
    """
    merged: dict[str, Any] = dict(vehicle)
    use_location = _is_newer(location.get("GPSDatetime"), vehicle.get("GPSDatetime"))
    if use_location:
        for field in LOCATION_OVERLAY_FIELDS:
            if field in location:
                merged[field] = location[field]
        if location.get("GPSDatetime") is not None:
            merged["GPSDatetime"] = location["GPSDatetime"]
    return merged, use_location


class CheryConnectCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch VehicleInfo + lastLocation, plus the slower extras.

    The poll runs every minute while the engine runs or the car charges,
    and at the user's interval otherwise.
    """

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
        self.idle_interval = update_interval
        self.extras = CheryExtras(api)

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
        vehicle, location = await self._fetch_vehicle()
        merged, use_location = merge_location(vehicle, location)
        self._log_refresh(vehicle, location, use_location)
        extras, new_alerts = await self.extras.async_refresh()
        merged.update(extras)
        self._fire_driver_alerts(new_alerts)
        self._adapt_interval(merged)
        return merged

    def _log_refresh(
        self, vehicle: dict[str, Any], location: dict[str, Any], use_location: bool
    ) -> None:
        """Log one info line per refresh.

        Info on purpose (Ziv): always visible, so the polling cadence can be
        checked without debug logging.
        """
        _LOGGER.info(
            "Chery Connect %s refreshed (every %s): %d fields, position from %s "
            "(GPS time VehicleInfo=%s, lastLocation=%s)",
            self.config_entry.title,
            self.update_interval,
            len(vehicle),
            "lastLocation" if use_location else "VehicleInfo",
            vehicle.get("GPSDatetime"),
            location.get("GPSDatetime"),
        )

    async def _fetch_vehicle(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch VehicleInfo and lastLocation, mapping errors for HA."""
        try:
            vehicle = await self.api.get_vehicle_info()
            location = await self.api.get_last_location()
        except InvalidAuthError as err:
            _LOGGER.debug("Refresh: token rejected, starting re-authentication")
            raise ConfigEntryAuthFailed("Chery Connect token rejected") from err
        except CheryApiError as err:
            _LOGGER.debug("Refresh failed: %s", err)
            raise UpdateFailed(f"Failed to fetch Chery data: {err}") from err
        return vehicle, location

    def _fire_driver_alerts(self, alerts: list[DriverAlert]) -> None:
        """Fire one bus event per new driver-behaviour alert."""
        for alert in alerts:
            _LOGGER.debug("New driver alert at %s", alert["time"])
            self.hass.bus.async_fire(
                EVENT_DRIVER_ALERT,
                {"config_entry_id": self.config_entry.entry_id, **alert},
            )

    def _adapt_interval(self, data: dict[str, Any]) -> None:
        """Poll every minute while driving or charging, else at the idle interval."""
        interval = ACTIVE_SCAN_INTERVAL if is_active(data) else self.idle_interval
        if interval != self.update_interval:
            _LOGGER.debug("Polling interval now %s", interval)
            self.update_interval = interval
