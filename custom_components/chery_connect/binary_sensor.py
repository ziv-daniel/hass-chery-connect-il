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

from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity


@dataclass(frozen=True, kw_only=True)
class CheryBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


def _is_charging(data: dict[str, Any]) -> bool | None:
    """Return True while the car reports ElectricChargeStatus == 1."""
    value = data.get("ElectricChargeStatus")
    if value is None:
        return None
    return str(value) == "1"


def _is_engine_on(data: dict[str, Any]) -> bool | None:
    """Return True while the car reports the engine on."""
    value = data.get("EngineOn")
    if value is None:
        return None
    return str(value) in ("1", "True", "true")


BINARY_SENSOR_DESCRIPTIONS: tuple[CheryBinarySensorDescription, ...] = (
    CheryBinarySensorDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        value_fn=_is_charging,
    ),
    CheryBinarySensorDescription(
        key="engine_on",
        name="Engine on",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_is_engine_on,
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
        """Return the binary sensor state."""
        return self.entity_description.value_fn(self.coordinator.data or {})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Chery Connect binary sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        CheryConnectBinarySensor(coordinator, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )
