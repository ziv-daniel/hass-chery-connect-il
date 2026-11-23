"""Binary sensors for the Chery Connect integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity, has_value

# The coordinator does all fetching; entities never poll on their own.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CheryBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description: the VehicleInfo field and its "on" values."""

    source: str
    on_values: frozenset[str]


BINARY_SENSOR_DESCRIPTIONS: tuple[CheryBinarySensorDescription, ...] = (
    CheryBinarySensorDescription(
        key="charging",
        translation_key="charging",
        source="ElectricChargeStatus",
        on_values=frozenset({"1"}),
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    CheryBinarySensorDescription(
        key="engine_on",
        translation_key="engine_on",
        source="EngineOn",
        on_values=frozenset({"1", "True", "true"}),
        device_class=BinarySensorDeviceClass.RUNNING,
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
        """Return True when the field holds one of the "on" values."""
        value = (self.coordinator.data or {}).get(self.entity_description.source)
        if value is None:
            return None
        return str(value) in self.entity_description.on_values


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors for the fields this vehicle reports."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    async_add_entities(
        CheryConnectBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
        if has_value(data, description.source)
    )
