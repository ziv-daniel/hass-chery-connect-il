"""Shared entity base for the Chery Connect integration."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CheryConnectCoordinator


class CheryConnectEntity(CoordinatorEntity[CheryConnectCoordinator]):
    """Base entity: device info and unique id from the vehicle number."""

    def __init__(self, coordinator: CheryConnectCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._key = key
        data = coordinator.data or {}
        self._v_number = str(data.get("Vnumber", ""))
        self._attr_unique_id = f"{self._v_number}_{key}" if self._v_number else key

    @property
    def device_info(self) -> DeviceInfo:
        """Return the vehicle as the device."""
        data: dict[str, Any] = self.coordinator.data or {}
        manufacturer = str(data.get("VehicleManu") or "Chery")
        model = str(data.get("VehicleModel") or "").strip()
        return DeviceInfo(
            identifiers={(DOMAIN, self._v_number)} if self._v_number else set(),
            manufacturer=manufacturer,
            model=model or "Chery Connect",
            name=f"Chery {model}".strip() if model else "Chery",
        )
