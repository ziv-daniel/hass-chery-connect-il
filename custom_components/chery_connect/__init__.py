"""The Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CheryApiError, CheryConnectApiClient, InvalidAuthError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import CheryConfigEntry, CheryConnectCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
]


def _scan_interval(entry: CheryConfigEntry) -> timedelta:
    """Return the configured scan interval, clamped to the 5-minute floor."""
    default = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
    try:
        minutes = int(entry.options.get(CONF_SCAN_INTERVAL, default))
    except TypeError, ValueError:
        minutes = default
    floor = int(MIN_SCAN_INTERVAL.total_seconds() // 60)
    return timedelta(minutes=max(minutes, floor))


async def async_setup_entry(hass: HomeAssistant, entry: CheryConfigEntry) -> bool:
    """Set up Chery Connect from a config entry."""
    api = CheryConnectApiClient(async_get_clientsession(hass), entry.data[CONF_TOKEN])

    # The app has no refresh token: a rejected token can only be fixed by reauth.
    _LOGGER.debug("Setting up %s: checking the stored token", entry.title)
    try:
        await api.test_token()
    except InvalidAuthError as err:
        _LOGGER.debug("Setup %s: token rejected, starting reauth", entry.title)
        raise ConfigEntryAuthFailed("Chery Connect token rejected") from err
    except CheryApiError as err:
        raise ConfigEntryNotReady(f"Chery Connect is unreachable: {err}") from err

    interval = _scan_interval(entry)
    _LOGGER.info(
        "Chery Connect %s: token valid, refreshing VehicleInfo + lastLocation every %s",
        entry.title,
        interval,
    )
    coordinator = CheryConnectCoordinator(hass, api, entry, interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CheryConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: CheryConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
