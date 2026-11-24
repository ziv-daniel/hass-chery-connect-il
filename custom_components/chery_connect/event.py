"""Event entity for driver-behaviour alerts (myCar tab 2)."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DRIVER_ALERT_EVENT_TYPE, EVENT_DRIVER_ALERT
from .coordinator import CheryConfigEntry, CheryConnectCoordinator
from .entity import CheryConnectEntity
from .extras import DriverAlert

# The coordinator does all fetching; entities never poll on their own.
PARALLEL_UPDATES = 0


class CheryDriverAlertEvent(CheryConnectEntity, EventEntity):
    """Mirrors each chery_connect_driver_alert bus event of this entry."""

    _attr_translation_key = "driver_alert"
    _attr_event_types = [DRIVER_ALERT_EVENT_TYPE]

    def __init__(self, coordinator: CheryConnectCoordinator) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator, "driver_alert")

    async def async_added_to_hass(self) -> None:
        """Listen for this entry's driver alerts."""
        await super().async_added_to_hass()
        entry_id = self.coordinator.config_entry.entry_id

        @callback
        def _is_ours(event_data: DriverAlert) -> bool:
            return event_data.get("config_entry_id") == entry_id

        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_DRIVER_ALERT, self._handle_alert, event_filter=_is_ours
            )
        )

    @callback
    def _handle_alert(self, event: Event[DriverAlert]) -> None:
        """Record the alert as this entity's latest event."""
        self._trigger_event(
            DRIVER_ALERT_EVENT_TYPE,
            {"message": event.data.get("message"), "time": event.data.get("time")},
        )
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CheryConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the driver-alert event entity."""
    async_add_entities([CheryDriverAlertEvent(entry.runtime_data)])
