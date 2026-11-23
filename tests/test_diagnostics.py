"""Tests for the Chery Connect diagnostics."""

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.chery_connect.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .const import PHONE, TOKEN, V_NUMBER


async def test_diagnostics_redacts_identity_and_location(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """No token, phone, plate, coordinates or address leave the diagnostics."""
    result = await async_get_config_entry_diagnostics(hass, init_integration)
    dumped = json.dumps(result)

    for secret in (TOKEN, PHONE, V_NUMBER, "32.08", "34.78", "Example St"):
        assert secret not in dumped, secret
    assert result["entry"]["data"]["token"] == "**REDACTED**"
    assert result["data"]["Address"] == "**REDACTED**"
    assert result["data"]["VehicleModel"] == "Tiggo 8 Pro"
    assert result["last_update_success"] is True
