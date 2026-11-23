"""Tests for setting up and unloading the Chery Connect integration."""

from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    API_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

from .const import V_NUMBER


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entry loads, exposes its coordinator and unloads cleanly."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.data["Vnumber"] == V_NUMBER

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("endpoint", "method"),
    [
        pytest.param("TestToken", "get", id="test_token"),
        pytest.param("VehicleInfo", "post", id="vehicle_info"),
        pytest.param("lastLocation", "post", id="last_location"),
    ],
)
async def test_rejected_token_starts_reauth(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    endpoint: str,
    method: str,
) -> None:
    """A 401 at any setup call ends in setup error plus a reauth flow."""
    responses = {
        "TestToken": ("get", {}),
        "VehicleInfo": ("post", vehicle_info),
        "lastLocation": ("post", last_location),
    }
    for name, (verb, payload) in responses.items():
        status = 401 if name == endpoint else 200
        getattr(aioclient_mock, verb)(
            f"{API_BASE_URL}{name}", json=payload, status=status
        )
    aioclient_mock.post(f"{API_BASE_URL}login/otp", json={"rescode": 1})
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id


@pytest.mark.parametrize(
    ("endpoint", "kwargs"),
    [
        pytest.param("TestToken", {"status": 503}, id="token_check_503"),
        pytest.param("TestToken", {"exc": TimeoutError}, id="token_check_timeout"),
        pytest.param("VehicleInfo", {"status": 500}, id="first_fetch_500"),
        pytest.param("VehicleInfo", {"text": "<html>maintenance</html>"}, id="html"),
    ],
)
async def test_unreachable_api_retries_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    last_location: dict[str, Any],
    endpoint: str,
    kwargs: dict[str, Any],
) -> None:
    """Network errors, 5xx and non-JSON bodies retry setup, no reauth."""
    if endpoint == "TestToken":
        aioclient_mock.get(f"{API_BASE_URL}TestToken", **kwargs)
    else:
        aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
        aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", **kwargs)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_device_registered_from_entry_unique_id(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The vehicle device is keyed by the entry's unique id."""
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, V_NUMBER), init_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Chery"
    assert device.model == "Tiggo 8 Pro"
    assert device.name == "Chery Tiggo 8 Pro"


async def test_token_expiring_later_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A 401 on a scheduled poll opens a reauth flow and marks entities unavailable."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", status=401)
    aioclient_mock.post(f"{API_BASE_URL}login/otp", json={"rescode": 1})

    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert hass.states.get("sensor.chery_tiggo_8_pro_odometer").state == "unavailable"


@pytest.mark.parametrize(
    ("options", "minutes"),
    [
        pytest.param({}, 10, id="default"),
        pytest.param({CONF_SCAN_INTERVAL: 30}, 30, id="custom"),
        pytest.param({CONF_SCAN_INTERVAL: 1}, 5, id="below_floor"),
        pytest.param({CONF_SCAN_INTERVAL: "bad"}, 10, id="invalid"),
    ],
)
async def test_scan_interval_option(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    options: dict[str, Any],
    minutes: int,
) -> None:
    """The poll interval follows the option, never below 5 minutes."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options=options)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    interval = mock_config_entry.runtime_data.update_interval
    assert interval.total_seconds() == minutes * 60


async def test_options_change_reloads_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Saving new options reloads the entry with the new poll interval."""
    hass.config_entries.async_update_entry(
        init_integration, options={CONF_SCAN_INTERVAL: 20}
    )
    await hass.async_block_till_done()

    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.update_interval.total_seconds() == 20 * 60
