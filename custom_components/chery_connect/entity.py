"""Shared entity base for the Chery Connect integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ELECTRIC_DESIGN_FIELD
from .coordinator import CheryConnectCoordinator, is_electric


class FieldDescription(Protocol):
    """The description fields that decide whether an entity is created."""

    @property
    def source(self) -> str:
        """The field the state is read from."""

    @property
    def presence(self) -> str | None:
        """The field that must have a value, when not ``source``."""

    @property
    def electric(self) -> bool:
        """True for battery and charging data, real only on electric cars."""


def creates_entity(data: dict[str, Any], description: FieldDescription) -> bool:
    """Return True when the vehicle should get the entity of ``description``.

    ``presence`` (default ``source``) is the field that must have a value. A
    field that is empty while idle, like the charge status text, points it at
    a field that always has one, so the entity exists and shows unknown.
    Battery and charging entities also need a car the server treats as
    electric: the others get fixed placeholder values.
    """
    if description.electric and not is_electric(data):
        return False
    return has_value(data, description.presence or description.source)


class KeyedDescription(FieldDescription, Protocol):
    """A field description with the key its unique_id is built from."""

    @property
    def key(self) -> str:
        """The entity key."""


def async_remove_placeholder_entities(
    hass: HomeAssistant,
    coordinator: CheryConnectCoordinator,
    domain: str,
    descriptions: Iterable[KeyedDescription],
) -> None:
    """Remove battery and charging entities of a car that is not electric.

    Up to 0.3.0b2 they were created from the placeholder values, so a plug-in
    hybrid showed a fixed 88 % battery that never charged. Nothing is removed
    when the field is missing, so an electric car whose refresh lacks it keeps
    its entities and history.
    """
    data = coordinator.data or {}
    if data.get(ELECTRIC_DESIGN_FIELD) in (None, "") or is_electric(data):
        return
    registry = er.async_get(hass)
    vehicle_id = coordinator.config_entry.unique_id
    for description in descriptions:
        if not description.electric:
            continue
        unique_id = f"{vehicle_id}_{description.key}"
        entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
        if entity_id is not None:
            registry.async_remove(entity_id)


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
