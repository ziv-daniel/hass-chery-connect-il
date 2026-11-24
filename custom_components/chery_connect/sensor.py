"""Sensors for the Chery Connect integration."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import parse_float, parse_odometer
from .const import (
    EXTRA_ACCELERATION_EVENTS,
    EXTRA_BRAKING_EVENTS,
    EXTRA_DISTANCE_MONTH,
    EXTRA_DISTANCE_MONTH_AVG,
    EXTRA_DISTANCE_TODAY,
    EXTRA_MESSAGES,
    EXTRA_SPEEDING_EVENTS,
    EXTRA_TRIP,
)
from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity, async_add_when_reported, has_value

# The coordinator does all fetching; entities never poll on their own.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CherySensorDescription(SensorEntityDescription):
    """Sensor description: the VehicleInfo field and how to parse it."""

    source: str
    value_fn: Callable[[Any], Any] = parse_float
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None


def _range_from_fuel_desc(desc: Any) -> float | None:
    """Range (km) from the first word of FualLevelDesc.

    UNVERIFIED for CheryTheme: the app derives kmToGo this way only
    under ``"NissanTheme"===PATH_THEME``. If the text does not start
    with a number, this returns None and the sensor is unknown.
    """
    if not isinstance(desc, str) or not desc:
        return None
    return parse_float(desc.split()[0])


def _parse_date(value: Any) -> date | None:
    """Parse an API date ("2027-03-15" or "2027-03-15T00:00:00") to a date.

    The API sends calendar dates without a timezone; a TIMESTAMP sensor
    rejects naive datetimes, so these are DATE sensors.
    """
    if not isinstance(value, str) or not value:
        return None
    if (parsed := dt_util.parse_datetime(value)) is not None:
        return parsed.date()
    return dt_util.parse_date(value)


_LEADING_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _voltage(value: Any) -> float | None:
    """Parse the 12V reading, which the app shows verbatim (e.g. "14.5V")."""
    if (number := parse_float(value)) is not None:
        return number
    match = _LEADING_NUMBER.match(str(value or "").strip())
    return float(match.group()) if match else None


def _count(value: Any) -> int | None:
    """Return a whole event count (already an int from the parser)."""
    return value if isinstance(value, int) else None


def _text(value: Any) -> str | None:
    """Return a trimmed text field, None when empty."""
    if value is None:
        return None
    return str(value).strip() or None


def _messages_count(value: Any) -> int | None:
    return value.get("count") if isinstance(value, dict) else None


def _messages_attrs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value.get(key) for key in ("latest_title", "latest_text", "latest_time")
    }


def _trip_end(value: Any) -> datetime | None:
    if not isinstance(value, dict) or not value.get("end"):
        return None
    return dt_util.parse_datetime(value["end"])


def _trip_attrs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {"start": value.get("start"), "points": value.get("points")}


def _distance(
    key: str, source: str, state_class: SensorStateClass
) -> CherySensorDescription:
    """Return a distance description for the myCar extras (km)."""
    return CherySensorDescription(
        key=key,
        translation_key=key,
        source=source,
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=state_class,
    )


def _driving_events(key: str) -> CherySensorDescription:
    """Return a monthly driving-event count description (myCar tab 4)."""
    return CherySensorDescription(
        key=key,
        translation_key=key,
        source=key,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_count,
    )


def _tyre(key: str, source: str) -> CherySensorDescription:
    """Return a tyre pressure description (PSI as the app shows it)."""
    return CherySensorDescription(
        key=key,
        translation_key=key,
        source=source,
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        suggested_unit_of_measurement=UnitOfPressure.PSI,
        suggested_display_precision=0,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


def _date(key: str, source: str) -> CherySensorDescription:
    """Return a calendar-date description (service, insurance, licence)."""
    return CherySensorDescription(
        key=key,
        translation_key=key,
        source=source,
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_parse_date,
    )


SENSOR_DESCRIPTIONS: tuple[CherySensorDescription, ...] = (
    CherySensorDescription(
        key="odometer",
        translation_key="odometer",
        source="Odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=parse_odometer,
    ),
    CherySensorDescription(
        key="fuel_level",
        translation_key="fuel_level",
        source="FualLevel",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    CherySensorDescription(
        key="range",
        translation_key="range",
        source="FualLevelDesc",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_range_from_fuel_desc,
    ),
    CherySensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        source="InputVoltage",
        value_fn=_voltage,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    CherySensorDescription(
        key="speed",
        translation_key="speed",
        source="Speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        # Only fresh while driving; the tracker carries it as an attribute.
        entity_registry_enabled_default=False,
    ),
    CherySensorDescription(
        key="electric_range",
        translation_key="electric_range",
        source="ElectricBatteryKM",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    CherySensorDescription(
        key="ev_battery_level",
        translation_key="ev_battery_level",
        source="ElectricBatteryStatus",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    CherySensorDescription(
        key="charge_status",
        translation_key="charge_status",
        source="ElectricBatteryChargeStatusText",
        value_fn=_text,
    ),
    _distance(
        EXTRA_DISTANCE_TODAY, EXTRA_DISTANCE_TODAY, SensorStateClass.TOTAL_INCREASING
    ),
    _distance(
        EXTRA_DISTANCE_MONTH, EXTRA_DISTANCE_MONTH, SensorStateClass.TOTAL_INCREASING
    ),
    _distance(
        EXTRA_DISTANCE_MONTH_AVG, EXTRA_DISTANCE_MONTH_AVG, SensorStateClass.MEASUREMENT
    ),
    CherySensorDescription(
        key="last_trip",
        translation_key="last_trip",
        source=EXTRA_TRIP,
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_trip_end,
        attrs_fn=_trip_attrs,
    ),
    CherySensorDescription(
        key="messages",
        translation_key="messages",
        source=EXTRA_MESSAGES,
        value_fn=_messages_count,
        attrs_fn=_messages_attrs,
    ),
    _driving_events(EXTRA_SPEEDING_EVENTS),
    _driving_events(EXTRA_ACCELERATION_EVENTS),
    _driving_events(EXTRA_BRAKING_EVENTS),
    _tyre("tyre_pressure_front_left", "Frontlefttyrepressure"),
    _tyre("tyre_pressure_front_right", "Frontrighttyrepressure"),
    _tyre("tyre_pressure_rear_left", "Rearlefttyrepressure"),
    _tyre("tyre_pressure_rear_right", "Rearrighttyrepressure"),
    _date("next_service", "NextTreatmentDate"),
    CherySensorDescription(
        key="next_service_type",
        translation_key="next_service_type",
        source="NextTreatmentType",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_text,
    ),
    _date("insurance_date", "InsureDate"),
    _date("licence_date", "LicensingDate"),
)


class CheryConnectSensor(CheryConnectEntity, SensorEntity):
    """A Chery Connect sensor."""

    entity_description: CherySensorDescription

    def __init__(
        self,
        coordinator: CheryConnectCoordinator,
        description: CherySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the parsed field from the latest coordinator data."""
        data = self.coordinator.data or {}
        return self.entity_description.value_fn(
            data.get(self.entity_description.source)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the description's attributes, if it has any."""
        if self.entity_description.attrs_fn is None:
            return None
        data = self.coordinator.data or {}
        return self.entity_description.attrs_fn(
            data.get(self.entity_description.source)
        )


@callback
def _async_migrate_tyre_unit(hass: HomeAssistant, entry: CheryConfigEntry) -> None:
    """Show existing tyre sensors in PSI.

    Up to 0.2.3 the suggested unit followed the unit system, so metric
    installs stored kPa. A unit the user picked themselves is kept.
    """
    registry = er.async_get(hass)
    tyre_ids = {
        f"{entry.unique_id}_{description.key}"
        for description in SENSOR_DESCRIPTIONS
        if description.suggested_unit_of_measurement == UnitOfPressure.PSI
    }
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "sensor" or reg_entry.unique_id not in tyre_ids:
            continue
        if CONF_UNIT_OF_MEASUREMENT in reg_entry.options.get("sensor", {}):
            continue
        private: dict[str, Any] = dict(reg_entry.options.get("sensor.private", {}))
        if private.get("suggested_unit_of_measurement") == UnitOfPressure.PSI:
            continue
        registry.async_update_entity_options(
            reg_entry.entity_id,
            "sensor.private",
            {**private, "suggested_unit_of_measurement": UnitOfPressure.PSI},
        )


# Extras come from separate, slower endpoints: a failed or empty first fetch
# must not hide them for good, so they are always created (unknown until set).
_EXTRA_SOURCES: frozenset[str] = frozenset(
    {
        EXTRA_DISTANCE_TODAY,
        EXTRA_DISTANCE_MONTH,
        EXTRA_DISTANCE_MONTH_AVG,
        EXTRA_TRIP,
        EXTRA_MESSAGES,
        EXTRA_SPEEDING_EVENTS,
        EXTRA_ACCELERATION_EVENTS,
        EXTRA_BRAKING_EVENTS,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for the fields this vehicle reports."""
    _async_migrate_tyre_unit(hass, entry)
    coordinator = entry.runtime_data
    async_add_when_reported(
        entry,
        coordinator,
        SENSOR_DESCRIPTIONS,
        lambda data, description: (
            description.source in _EXTRA_SOURCES or has_value(data, description.source)
        ),
        lambda description: CheryConnectSensor(coordinator, description),
        async_add_entities,
    )
