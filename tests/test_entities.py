"""Tests for the sensor, binary sensor and device tracker entities."""

from typing import Any

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    load_json_object_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    API_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
)
from custom_components.chery_connect.sensor import _EXTRA_SOURCES, SENSOR_DESCRIPTIONS

from .const import V_NUMBER

EXPECTED = load_json_object_fixture("expected_states.json")
# Unique-id suffixes of the sensors fed by the extra endpoints.
EXTRAS_KEYS = {
    description.key
    for description in SENSOR_DESCRIPTIONS
    if description.source in _EXTRA_SOURCES
}


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
    """No enabled entity is created that the expectations do not cover."""
    created = {
        state.entity_id
        for state in hass.states.async_all()
        if not state.entity_id.startswith("zone.")
    }
    assert created == set(EXPECTED)


async def test_only_reported_fields_create_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    mock_extras: dict[str, Any],
) -> None:
    """Empty payloads create only the always-present entities, with stable ids.

    Extras sensors always exist (unknown until their endpoint answers), and an
    empty getMessages answer still means "no messages" (count 0).
    """
    for name in mock_extras:
        mock_extras[name] = {}
    await _setup_with(hass, mock_config_entry, aioclient_mock, {}, {})

    created = sorted(
        s.entity_id for s in hass.states.async_all() if "chery" in s.entity_id
    )
    assert created == [
        "device_tracker.chery_location",
        "event.chery_driver_alert",
        "sensor.chery_distance_this_month",
        "sensor.chery_distance_today",
        "sensor.chery_harsh_acceleration_events_this_month",
        "sensor.chery_harsh_braking_events_this_month",
        "sensor.chery_last_trip",
        "sensor.chery_messages",
        "sensor.chery_monthly_distance_average",
        "sensor.chery_speeding_events_this_month",
    ]
    assert hass.states.get("sensor.chery_last_trip").state == "unknown"
    assert hass.states.get("device_tracker.chery_location").state == "unknown"
    assert hass.states.get("sensor.chery_messages").state == "0"


async def test_electric_fields_create_entities(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A vehicle that reports an electric range gets that sensor."""
    vehicle_info["ElectricBatteryKM"] = "55"
    await _setup_with(
        hass, mock_config_entry, aioclient_mock, vehicle_info, last_location
    )
    assert hass.states.get("sensor.chery_tiggo_8_pro_electric_range").state == "55.0"


async def test_entity_metadata(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Names come from translations; diagnostics and speed are categorised."""
    odometer = hass.states.get("sensor.chery_tiggo_8_pro_odometer")
    assert odometer.attributes["friendly_name"] == "Chery Tiggo 8 Pro Odometer"
    tyre = entity_registry.async_get(
        "sensor.chery_tiggo_8_pro_tyre_pressure_front_left"
    )
    assert tyre.entity_category is EntityCategory.DIAGNOSTIC
    assert tyre.translation_key == "tyre_pressure_front_left"
    speed = entity_registry.async_get("sensor.chery_tiggo_8_pro_speed")
    assert speed.disabled_by is er.RegistryEntryDisabler.INTEGRATION


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


async def test_fields_dropped_later_become_unknown(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Entities created at setup go unknown when a later poll omits the field."""
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json={})
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json={})

    freezer.tick(DEFAULT_SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    # The extras are cached for EXTRAS_REFRESH_INTERVAL, and the event
    # entity is not fed by VehicleInfo, so only VehicleInfo entities drop.
    for entity_id in EXPECTED:
        key = entity_registry.async_get(entity_id).unique_id.removeprefix(
            f"{V_NUMBER}_"
        )
        if key in EXTRAS_KEYS or entity_id.startswith("event."):
            continue
        assert hass.states.get(entity_id).state == "unknown", entity_id


TYRE_FL = "sensor.chery_tiggo_8_pro_tyre_pressure_front_left"


@pytest.mark.parametrize(
    ("options", "expected_unit", "expected_precision"),
    [
        pytest.param(
            {"sensor.private": {"suggested_unit_of_measurement": "kPa"}},
            "psi",
            0,
            id="metric_default_migrates",
        ),
        pytest.param(
            {
                "sensor": {"unit_of_measurement": "bar"},
                "sensor.private": {"suggested_unit_of_measurement": "kPa"},
            },
            "bar",
            1,
            id="user_choice_kept",
        ),
    ],
)
async def test_tyre_unit_migration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    entity_registry: er.EntityRegistry,
    options: dict[str, dict[str, str]],
    expected_unit: str,
    expected_precision: int,
) -> None:
    """Tyre sensors registered in kPa (pre-0.2.4) switch to PSI unless the user chose a unit."""
    mock_config_entry.add_to_hass(hass)
    entity_registry.async_get_or_create(
        "sensor",
        "chery_connect",
        f"{V_NUMBER}_tyre_pressure_front_left",
        config_entry=mock_config_entry,
        suggested_object_id="chery_tiggo_8_pro_tyre_pressure_front_left",
    )
    for domain, domain_options in options.items():
        entity_registry.async_update_entity_options(TYRE_FL, domain, domain_options)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(TYRE_FL)
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == expected_unit
    assert (
        entity_registry.async_get(TYRE_FL).options["sensor"][
            "suggested_display_precision"
        ]
        == expected_precision
    )


TYRE_LOW = "binary_sensor.chery_tiggo_8_pro_tyre_pressure_low"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        pytest.param({}, "off", id="all_within_allowed_difference"),
        pytest.param({"Rearlefttyrepressure": "33.5"}, "on", id="rear_low"),
        pytest.param(
            {"Frontlefttyrepressure": "35", "maxDiff": None}, "off", id="default_diff"
        ),
        pytest.param({"maxDiff": "0.5"}, "on", id="strict_diff"),
        pytest.param(
            {
                "Frontlefttyrepressure": "0",
                "Frontrighttyrepressure": "0",
                "Rearlefttyrepressure": "0",
                "Rearrighttyrepressure": "0",
            },
            "unknown",
            id="sensors_asleep",
        ),
        pytest.param(
            {"PSI_BACK": "", "Frontlefttyrepressure": "30"}, "on", id="front_only"
        ),
    ],
)
async def test_tyre_pressure_low(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    changes: dict[str, Any],
    expected: str,
) -> None:
    """Low when any tyre is below the recommended PSI minus the allowed difference."""
    vehicle_info.update(changes)
    await _setup_with(
        hass, mock_config_entry, aioclient_mock, vehicle_info, last_location
    )
    assert hass.states.get(TYRE_LOW).state == expected


async def test_tyre_pressure_low_attributes(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The recommended pressures and allowed difference are attributes."""
    attributes = hass.states.get(TYRE_LOW).attributes
    assert attributes["recommended_front"] == 36.0
    assert attributes["recommended_rear"] == 36.0
    assert attributes["max_difference"] == 2.0


async def test_no_recommendation_no_tyre_low_entity(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Without PSI_FRONT the vehicle gets no tyre-low entity."""
    del vehicle_info["PSI_FRONT"]
    await _setup_with(
        hass, mock_config_entry, aioclient_mock, vehicle_info, last_location
    )
    assert hass.states.get(TYRE_LOW) is None


async def test_ev_battery_and_charge_status(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A plug-in car gets the EV battery level and the charge status text."""
    vehicle_info["ElectricBatteryStatus"] = "64"
    vehicle_info["ElectricBatteryChargeStatusText"] = " Charging "
    await _setup_with(
        hass, mock_config_entry, aioclient_mock, vehicle_info, last_location
    )
    battery = hass.states.get("sensor.chery_tiggo_8_pro_ev_battery")
    assert battery.state == "64.0"
    assert battery.attributes[ATTR_DEVICE_CLASS] == "battery"
    assert battery.attributes[ATTR_UNIT_OF_MEASUREMENT] == "%"
    status = hass.states.get("sensor.chery_tiggo_8_pro_charge_status")
    assert status.state == "Charging"
