"""Shared entity base for the Chery Connect integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CheryConnectCoordinator


class CheryConnectEntity(CoordinatorEntity[CheryConnectCoordinator]):
    """Base entity: one device per vehicle, keyed by the config entry."""

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
