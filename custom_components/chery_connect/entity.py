"""Shared entity base for the Chery Connect integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CheryConnectCoordinator


def has_value(data: dict[str, Any], source: str) -> bool:
    """Return True when the vehicle reports the field at all.

    Used at setup so a petrol car gets no charging or electric-range entity.
    """
    return data.get(source) not in (None, "")


def async_add_when_reported[DescriptionT: EntityDescription](
    entry: ConfigEntry,
    coordinator: CheryConnectCoordinator,
    descriptions: Iterable[DescriptionT],
    is_reported: Callable[[dict[str, Any], DescriptionT], bool],
    make_entity: Callable[[DescriptionT], Entity],
    async_add_entities: Callable[[Iterable[Entity]], None],
) -> None:
    """Add each entity once its field is reported, now or on a later refresh.

    Fields such as the charge status text are empty while the car is parked
    and only show up while it charges, so checking the first refresh alone
    would never create them.
    """
    pending = list(descriptions)

    @callback
    def _add_reported() -> None:
        data = coordinator.data or {}
        reported = [d for d in pending if is_reported(data, d)]
        if not reported:
            return
        for description in reported:
            pending.remove(description)
        async_add_entities(make_entity(d) for d in reported)

    _add_reported()
    if pending:
        entry.async_on_unload(coordinator.async_add_listener(_add_reported))


class CheryConnectEntity(CoordinatorEntity[CheryConnectCoordinator]):
    """Base entity: one device per vehicle, keyed by the config entry."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CheryConnectCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        # entry.unique_id is the vehicle number set by the config flow; unlike
        # coordinator data it exists even before the first successful fetch.
        vehicle_id = coordinator.config_entry.unique_id
        self._attr_unique_id = f"{vehicle_id}_{key}"
        data = coordinator.data or {}
        model = str(data.get("VehicleModel") or "").strip()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(vehicle_id))},
            manufacturer=str(data.get("VehicleManu") or "Chery"),
            model=model or None,
            name=f"Chery {model}" if model else "Chery",
        )
