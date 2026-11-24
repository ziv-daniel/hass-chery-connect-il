"""DataUpdateCoordinator for the Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CheryApiError,
    CheryConnectApiClient,
    InvalidAuthError,
    parse_api_time,
    parse_ev_tile,
    parse_float,
)
from .const import (
    ACTIVE_SCAN_INTERVAL,
    CHARGING_ON_VALUES,
    CONF_IPOINTER_REFRESH_TOKEN,
    DOMAIN,
    ELECTRIC_DESIGN_FIELD,
    ELECTRIC_DESIGNS,
    ENGINE_ON_VALUES,
    EV_SOURCE_IPOINTER,
    EVENT_DRIVER_ALERT,
    EXTRA_EV_SOURCE,
    IPOINTER_EV_FIELDS,
    ISSUE_IPOINTER_AUTH,
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


def is_electric(data: dict[str, Any]) -> bool:
    """Return True when the battery and charging data are real.

    Either the Chery server marks the car electric, or the data comes from
    iPointer.
    """
    return (
        data.get(EXTRA_EV_SOURCE) == EV_SOURCE_IPOINTER
        or str(data.get(ELECTRIC_DESIGN_FIELD)) in ELECTRIC_DESIGNS
    )


def apply_ev_tile(data: dict[str, Any], tile: dict[str, Any] | None) -> None:
    """Replace the Chery Electric* fields with the iPointer battery tile.

    Without a tile (iPointer failed) the fields become None, so the
    entities show unknown instead of the Chery placeholders.
    """
    data[EXTRA_EV_SOURCE] = EV_SOURCE_IPOINTER
    for field, tile_field in IPOINTER_EV_FIELDS:
        data[field] = tile.get(tile_field) if tile is not None else None


def ev_auth_issue_id(entry: ConfigEntry) -> str:
    """Return the id of the entry's iPointer login repair issue."""
    return f"{ISSUE_IPOINTER_AUTH}_{entry.entry_id}"


def delete_ev_auth_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the entry's iPointer login repair issue, if any."""
    ir.async_delete_issue(hass, DOMAIN, ev_auth_issue_id(entry))


def is_charging(data: dict[str, Any]) -> bool:
    """Return True while an electric car charges."""
    return (
        is_electric(data)
        and str(data.get("ElectricChargeStatus")) in CHARGING_ON_VALUES
    )


def is_active(data: dict[str, Any]) -> bool:
    """Return True while the car moves, its engine runs or it charges.

    A plug-in hybrid driving on electricity reports EngineOn off, so speed
    counts as driving too.
    """
    speed = parse_float(data.get("Speed"))
    return (
        (speed is not None and speed > 0)
        or str(data.get("EngineOn")) in ENGINE_ON_VALUES
        or is_charging(data)
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
        ev_api: CheryConnectApiClient | None = None,
        *,
        ev_shared: bool = False,
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
        self.ev_api = ev_api
        self._ev_auth_failed = False
        # ev_api holds the Chery login rather than an iPointer one.
        self.ev_shared = ev_shared
        self._ev_shared_ok = False
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
        if self.ev_shared:
            await self._apply_shared_ev_tile(merged)
        elif self.ev_api is not None:
            apply_ev_tile(merged, await self._fetch_ev_tile(self.ev_api))
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

    async def _fetch_ev_tile(
        self, ev_api: CheryConnectApiClient
    ) -> dict[str, Any] | None:
        """Fetch the iPointer battery tile; None when it is unavailable.

        iPointer is optional: its failures never fail the refresh. A
        rejected token is renewed once with the refresh token; if that
        fails too, a repair issue asks the user to connect iPointer again.
        """
        try:
            try:
                info = await ev_api.get_vehicle_info()
            except InvalidAuthError:
                await self._renew_ev_token(ev_api)
                info = await ev_api.get_vehicle_info()
        except InvalidAuthError:
            if not self._ev_auth_failed:
                _LOGGER.warning(
                    "iPointer rejected the login for %s; connect iPointer again "
                    "in the integration options",
                    self.config_entry.title,
                )
            self._set_ev_auth_issue(active=True)
            return None
        except CheryApiError as err:
            _LOGGER.debug("iPointer refresh failed: %s", err)
            return None
        self._set_ev_auth_issue(active=False)
        tile = parse_ev_tile(info)
        if tile is None:
            _LOGGER.debug("iPointer VehicleInfo has no usable EVTile")
        return tile

    @property
    def ev_login(self) -> str:
        """Describe the iPointer login for diagnostics."""
        if not self.ev_shared:
            return "ipointer"
        if self.ev_api is None:
            return "chery_login_rejected"
        if self._ev_shared_ok:
            return "chery_login_ok"
        return "chery_login_no_battery_data"

    async def _apply_shared_ev_tile(self, data: dict[str, Any]) -> None:
        """Add the iPointer battery tile fetched with the Chery login.

        Until a tile has arrived once, a failure leaves the Chery data as
        it is: the car may have no iPointer battery data at all. After that,
        a failure shows unknown, as with a separate iPointer login. A
        rejected login stops the attempts until the entry reloads.
        """
        tile = None
        if self.ev_api is not None:
            try:
                tile = parse_ev_tile(await self.ev_api.get_vehicle_info())
            except InvalidAuthError:
                _LOGGER.info(
                    "iPointer does not accept the Chery Connect login for %s; "
                    "for battery data, connect iPointer in the integration options",
                    self.config_entry.title,
                )
                self.ev_api = None
            except CheryApiError as err:
                _LOGGER.debug("iPointer refresh with the Chery login failed: %s", err)
        if tile is not None and not self._ev_shared_ok:
            _LOGGER.info(
                "Battery data for %s comes from iPointer with the Chery login",
                self.config_entry.title,
            )
            self._ev_shared_ok = True
        if self._ev_shared_ok:
            apply_ev_tile(data, tile)

    async def _renew_ev_token(self, ev_api: CheryConnectApiClient) -> None:
        """Get a new iPointer token with the stored refresh token.

        The new token is kept in memory only; after a restart the refresh
        token renews it again. Raises InvalidAuthError when that fails.
        """
        refresh_token = self.config_entry.data.get(CONF_IPOINTER_REFRESH_TOKEN)
        if not refresh_token:
            raise InvalidAuthError("No iPointer refresh token")
        _LOGGER.debug("iPointer token rejected, renewing it")
        await ev_api.refresh(refresh_token)

    def _set_ev_auth_issue(self, *, active: bool) -> None:
        """Raise or clear the repair issue for a dead iPointer login."""
        self._ev_auth_failed = active
        if not active:
            delete_ev_auth_issue(self.hass, self.config_entry)
            return
        issue_id = ev_auth_issue_id(self.config_entry)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_IPOINTER_AUTH,
            translation_placeholders={"entry_title": self.config_entry.title},
        )

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
