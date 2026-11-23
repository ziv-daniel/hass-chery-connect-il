"""The Chery Connect integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CheryConnectApiClient, InvalidAuthError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import CheryConnectCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
]


def _scan_interval(entry: ConfigEntry) -> timedelta:
    """Return the configured scan interval, clamped to the 5-minute floor."""
    minutes = entry.options.get(
        CONF_SCAN_INTERVAL,
        int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
    )
    try:
        minutes_int = int(minutes)
    except TypeError, ValueError:
        minutes_int = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
    floor = int(MIN_SCAN_INTERVAL.total_seconds() // 60)
    return timedelta(minutes=max(minutes_int, floor))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Chery Connect from a config entry."""
    session = async_get_clientsession(hass)
    api = CheryConnectApiClient(session, entry.data.get(CONF_TOKEN))

    # Validate the stored token up front, like the app's TestToken call.
    # A dead token raises InvalidAuthError here and HA starts the reauth
    # flow instead of loading entities that can never update.
    try:
        await api.test_token()
    except InvalidAuthError:
        _LOGGER.warning("Stored Chery Connect token rejected; reauth required")
        raise
    except Exception as err:  # noqa: BLE001 - a failed check must not block setup
        _LOGGER.warning("Chery Connect token check failed: %s", err)

    coordinator = CheryConnectCoordinator(hass, api, entry, _scan_interval(entry))

    # async_refresh (not async_config_entry_first_refresh): a failed first
    # fetch should degrade to unavailable entities, not leave the entry in
    # setup_retry with nothing loaded.
    await coordinator.async_refresh()
    if not coordinator.last_update_success:
        _LOGGER.warning(
            "Initial Chery Connect fetch failed; entities will report "
            "unavailable until the next successful update"
        )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Chery Connect set up")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
