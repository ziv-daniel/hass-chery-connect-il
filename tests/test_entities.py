"""Tests for the sensor, binary sensor and device tracker entities."""

from typing import Any

import pytest
from homeassistant.const import ATTR_DEVICE_CLASS, ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_json_object_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import API_BASE_URL

from .const import V_NUMBER

EXPECTED = load_json_object_fixture("expected_states.json")


async def _setup_with(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle: dict[str, Any],
    location: dict[str, Any],
) -> None:
    """Set up the entry with the given VehicleInfo and lastLocation payloads."""
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=location)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize("entity_id", sorted(EXPECTED))
async def test_entity_state(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    entity_id: str,
) -> None:
    """Every entity reports the value, unit and class of the fixture payload."""
    expected = EXPECTED[entity_id]
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == expected["state"]
    assert state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == expected["unit"]
    assert state.attributes.get(ATTR_DEVICE_CLASS) == expected["device_class"]
    for attribute in ("latitude", "longitude"):
        if attribute in expected:
            assert state.attributes[attribute] == expected[attribute]
    registry_entry = entity_registry.async_get(entity_id)
    assert registry_entry.unique_id.startswith(f"{V_NUMBER}_")


async def test_entity_set_is_complete(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """No entity is created that the expectations do not cover."""
    created = {
        state.entity_id
        for state in hass.states.async_all()
        if not state.entity_id.startswith("zone.")
    }
    assert created == set(EXPECTED)


async def test_missing_fields_are_unknown(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """An empty payload leaves every entity unknown, with stable unique ids."""
    await _setup_with(hass, mock_config_entry, aioclient_mock, {}, {})

    for entity_id in EXPECTED:
        # Without VehicleModel the device, and so the entity ids, use "chery".
        fallback_id = entity_id.replace("chery_tiggo_8_pro", "chery")
        assert hass.states.get(fallback_id).state == "unknown", fallback_id


@pytest.mark.parametrize(
    ("field", "value", "entity_id", "expected"),
    [
        pytest.param(
            "InsureDate",
            "not a date",
            "sensor.chery_tiggo_8_pro_insurance_date",
            "unknown",
            id="bad_date",
        ),
        pytest.param(
            "LicensingDate",
            "2027-06-30T23:30:00",
            "sensor.chery_tiggo_8_pro_licence_date",
            "2027-06-30",
            id="naive_late_datetime_keeps_calendar_day",
        ),
        pytest.param(
            "FualLevelDesc",
            "Full",
            "sensor.chery_tiggo_8_pro_range",
            "unknown",
            id="range_without_number",
        ),
        pytest.param(
            "ElectricChargeStatus",
            1,
            "binary_sensor.chery_tiggo_8_pro_charging",
            "on",
            id="charging",
        ),
        pytest.param(
            "EngineOn",
            "True",
            "binary_sensor.chery_tiggo_8_pro_engine_on",
            "on",
            id="engine_on",
        ),
    ],
)
async def test_field_parsing(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    field: str,
    value: Any,
    entity_id: str,
    expected: str,
) -> None:
    """Edge-case API values map to the right state instead of crashing."""
    vehicle_info[field] = value
    await _setup_with(
        hass, mock_config_entry, aioclient_mock, vehicle_info, last_location
    )
    assert hass.states.get(entity_id).state == expected
