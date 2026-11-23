"""Sensors for the Chery Connect integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import parse_float, parse_odometer
from .const import DOMAIN
from .coordinator import CheryConnectCoordinator
from .entity import CheryConnectEntity


@dataclass(frozen=True, kw_only=True)
class CherySensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor over VehicleInfo data."""

    value_fn: Callable[[dict[str, Any]], Any]


def _range_from_fuel_desc(data: dict[str, Any]) -> float | None:
    """Range (km) from the first word of FualLevelDesc.

    UNVERIFIED for CheryTheme: the app derives kmToGo this way only
    under ``"NissanTheme"===PATH_THEME``. If the text does not start
    with a number, this returns None and the sensor is unknown.
    """
    desc = data.get("FualLevelDesc")
    if not isinstance(desc, str) or not desc:
        return None
    return parse_float(desc.split()[0])


def _parse_date(value: Any) -> datetime | None:
    """Parse a date/datetime string from the API into an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is not None:
        return parsed
    date = dt_util.parse_date(value)
    if date is None:
        return None
    return datetime.combine(date, time.min, tzinfo=timezone.utc)


SENSOR_DESCRIPTIONS: tuple[CherySensorDescription, ...] = (
    CherySensorDescription(
        key="odometer",
        name="Odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: parse_odometer(data.get("Odometer")),
    ),
    CherySensorDescription(
        key="fuel_level",
        name="Fuel level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("FualLevel")),
    ),
    CherySensorDescription(
        key="range",
        name="Range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_range_from_fuel_desc,
    ),
    CherySensorDescription(
        key="battery_voltage",
        name="12V battery voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("InputVoltage")),
    ),
    CherySensorDescription(
        key="speed",
        name="Speed",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("Speed")),
    ),
    CherySensorDescription(
        key="electric_range",
        name="Electric range",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("ElectricBatteryKM")),
    ),
    CherySensorDescription(
        key="tyre_pressure_front_left",
        name="Tyre pressure front left",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("Frontlefttyrepressure")),
    ),
    CherySensorDescription(
        key="tyre_pressure_front_right",
        name="Tyre pressure front right",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("Frontrighttyrepressure")),
    ),
    CherySensorDescription(
        key="tyre_pressure_rear_left",
        name="Tyre pressure rear left",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("Rearlefttyrepressure")),
    ),
    CherySensorDescription(
        key="tyre_pressure_rear_right",
        name="Tyre pressure rear right",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.PSI,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: parse_float(data.get("Rearrighttyrepressure")),
    ),
    CherySensorDescription(
        key="next_service",
        name="Next service",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _parse_date(data.get("NextTreatmentDate")),
    ),
    CherySensorDescription(
        key="insurance_date",
        name="Insurance date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _parse_date(data.get("InsureDate")),
    ),
    CherySensorDescription(
        key="licence_date",
        name="Licence date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: _parse_date(data.get("LicensingDate")),
    ),
)


class CheryConnectSensor(CheryConnectEntity, SensorEntity):
    """A Chery Connect sensor."""

    def __init__(
        self,
        coordinator: CheryConnectCoordinator,
        description: CherySensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> Any:
        """Return the sensor value from the latest coordinator data."""
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the GPS time and address for context."""
        data = self.coordinator.data or {}
        return {
            "gps_datetime": data.get("GPSDatetime"),
            "address": data.get("Address"),
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Chery Connect sensors from a config entry."""
    coordinator: CheryConnectCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities(
        CheryConnectSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )
