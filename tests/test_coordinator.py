"""Tests for merging VehicleInfo with lastLocation."""

from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    ACTIVE_SCAN_INTERVAL,
    API_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
)

from .const import TOKEN


@pytest.mark.parametrize(
    ("vehicle_time", "location_time", "expected_lat", "expected_time"),
    [
        pytest.param(
            "2026-11-23T10:00:00",
            "2026-11-23T10:05:00",
            "32.0850",
            "2026-11-23T10:05:00",
            id="location_newer",
        ),
        pytest.param(
            "2026-11-23T10:10:00",
            "2026-11-23T10:05:00",
            "32.0800",
            "2026-11-23T10:10:00",
            id="location_older",
        ),
        pytest.param(
            None,
            "2026-11-23T10:05:00",
            "32.0850",
            "2026-11-23T10:05:00",
            id="no_vehicle_time",
        ),
        pytest.param(
            "2026-11-23T10:00:00",
            None,
            "32.0800",
            "2026-11-23T10:00:00",
            id="no_location_time",
        ),
        pytest.param(
            "2026-11-23T10:00:00Z",
            "2026-11-23T12:01:00+02:00",
            "32.0850",
            "2026-11-23T12:01:00+02:00",
            id="mixed_offsets",
        ),
        pytest.param("garbage-a", "garbage-b", "32.0850", "garbage-b", id="unparsable"),
        pytest.param(1700000000, 1700000100, "32.0850", 1700000100, id="not_a_string"),
    ],
)
async def test_location_overlay(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    vehicle_time: str | int | None,
    location_time: str | int | None,
    expected_lat: str,
    expected_time: str | int | None,
) -> None:
    """LastLocation fields win only when its GPS time is strictly newer."""
    vehicle_info["GPSDatetime"] = vehicle_time
    last_location["GPSDatetime"] = location_time
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle_info)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    data = mock_config_entry.runtime_data.data
    assert data["Latitude"] == expected_lat
    assert data["GPSDatetime"] == expected_time
    assert data["Odometer"] == "12,345"
    assert mock_config_entry.runtime_data.api.token == TOKEN


async def test_naive_gps_time_is_israel_local(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A naive 11:30 is 09:30 UTC in winter, so it is older than 10:00 UTC."""
    vehicle_info["GPSDatetime"] = "2026-11-23T10:00:00Z"
    last_location["GPSDatetime"] = "2026-11-23T11:30:00"
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle_info)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.data["Latitude"] == vehicle_info["Latitude"]


async def test_engine_on_taken_from_newer_location(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A newer lastLocation EngineOn wins over the stale VehicleInfo one."""
    last_location["EngineOn"] = "1"
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle_info)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.chery_tiggo_8_pro_engine_on").state == "on"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("EngineOn", "1", id="driving"),
        pytest.param("ElectricChargeStatus", 1, id="charging"),
    ],
)
async def test_interval_adapts_to_activity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    freezer: FrozenDateTimeFactory,
    field: str,
    value: Any,
) -> None:
    """Polls every minute while driving or charging, then back to idle."""
    active = dict(vehicle_info, **{field: value})
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=active)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_config_entry.runtime_data
    assert coordinator.update_interval == ACTIVE_SCAN_INTERVAL

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle_info)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    freezer.tick(ACTIVE_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 2
    assert coordinator.update_interval == DEFAULT_SCAN_INTERVAL
