"""Binary sensors for the Chery Connect integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import parse_float
from .const import (
    CHARGING_ON_VALUES,
    DEFAULT_TYRE_MAX_DIFF,
    ENGINE_ON_VALUES,
    TYRE_AXLES,
)
from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity, async_add_when_reported, has_value

# The coordinator does all fetching; entities never poll on their own.
PARALLEL_UPDATES = 0


def _recommended(data: dict[str, Any], field: str) -> float | None:
    """Recommended PSI; the server sends -1 (or 0) when it has none."""
    value = parse_float(data.get(field))
    return value if value is not None and value > 0 else None


def _tyre_max_diff(data: dict[str, Any]) -> float:
    max_diff = parse_float(data.get("maxDiff"))
    return DEFAULT_TYRE_MAX_DIFF if max_diff is None else max_diff


def tyre_pressure_low(data: dict[str, Any]) -> bool | None:
    """Return True when any tyre is below the recommended PSI minus maxDiff.

    A reading of 0 means the tyre sensors are asleep, not a flat tyre, so
    it is ignored. None when there is no recommendation or no reading
    (the app then shows a false "pressure not OK" with "-1 PSI").
    """
    max_diff = _tyre_max_diff(data)
    lows: list[bool] = []
    for required_field, tyre_fields in TYRE_AXLES:
        required = _recommended(data, required_field)
        if required is None:
            continue
        for tyre_field in tyre_fields:
            reading = parse_float(data.get(tyre_field))
            if reading is not None and reading > 0:
                lows.append(reading < required - max_diff)
    return any(lows) if lows else None


def tyre_attributes(data: dict[str, Any]) -> dict[str, Any]:
    """Recommended pressures (PSI) and the allowed difference."""
    return {
        "recommended_front": _recommended(data, "PSI_FRONT"),
        "recommended_rear": _recommended(data, "PSI_BACK"),
        "max_difference": _tyre_max_diff(data),
    }


@dataclass(frozen=True, kw_only=True)
class CheryBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description.

    ``source`` decides whether the vehicle gets the entity; the state is
    ``source`` matched against ``on_values``, or ``is_on_fn`` on all data.
    """

    source: str
    on_values: frozenset[str] = frozenset()
    is_on_fn: Callable[[dict[str, Any]], bool | None] | None = None
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


BINARY_SENSOR_DESCRIPTIONS: tuple[CheryBinarySensorDescription, ...] = (
    CheryBinarySensorDescription(
        key="charging",
        translation_key="charging",
        source="ElectricChargeStatus",
        on_values=CHARGING_ON_VALUES,
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    CheryBinarySensorDescription(
        key="engine_on",
        translation_key="engine_on",
        source="EngineOn",
        on_values=ENGINE_ON_VALUES,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    CheryBinarySensorDescription(
        key="tyre_pressure_low",
        translation_key="tyre_pressure_low",
        source="PSI_FRONT",
        is_on_fn=tyre_pressure_low,
        attrs_fn=tyre_attributes,
        device_class=BinarySensorDeviceClass.PROBLEM,
    ),
)


class CheryConnectBinarySensor(CheryConnectEntity, BinarySensorEntity):
    """A Chery Connect binary sensor."""

    entity_description: CheryBinarySensorDescription

    def __init__(
        self,
        coordinator: CheryConnectCoordinator,
        description: CheryBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state from is_on_fn, or the field against on_values."""
        data = self.coordinator.data or {}
        if self.entity_description.is_on_fn is not None:
            return self.entity_description.is_on_fn(data)
        value = data.get(self.entity_description.source)
        if value is None:
            return None
        return str(value) in self.entity_description.on_values

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the description's attributes, if it has any."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or {})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors for the fields this vehicle reports."""
    coordinator = entry.runtime_data
    async_add_when_reported(
        entry,
        coordinator,
        BINARY_SENSOR_DESCRIPTIONS,
        lambda data, description: has_value(data, description.source),
        lambda description: CheryConnectBinarySensor(coordinator, description),
        async_add_entities,
    )
