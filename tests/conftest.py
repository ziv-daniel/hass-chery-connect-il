"""Shared fixtures for the Chery Connect tests.

The fixture payloads are synthetic: field names follow the app's API
contract, values are invented (no real phone, plate or location).
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    load_json_object_fixture,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    API_BASE_URL,
    CONF_MOBILE_PHONE,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DOMAIN,
)

from .const import PHONE, TOKEN, V_NUMBER


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def vehicle_info() -> dict[str, Any]:
    """Return a VehicleInfo payload."""
    return load_json_object_fixture("vehicle_info.json")


@pytest.fixture
def last_location() -> dict[str, Any]:
    """Return a lastLocation payload."""
    return load_json_object_fixture("last_location.json")


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured Chery Connect entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Chery {V_NUMBER}",
        unique_id=V_NUMBER,
        data={CONF_MOBILE_PHONE: PHONE, CONF_V_NUMBER: V_NUMBER, CONF_TOKEN: TOKEN},
    )


@pytest.fixture
def mock_api(
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> AiohttpClientMocker:
    """Answer every data endpoint with the fixture payloads."""
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=vehicle_info)
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    return aioclient_mock


@pytest.fixture
def platforms() -> list[str]:
    """Platforms to load; tests can narrow it."""
    return ["sensor", "binary_sensor", "device_tracker"]


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    platforms: list[str],
) -> Generator[MockConfigEntry]:
    """Set up the integration with the fixture payloads."""
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.chery_connect.PLATFORMS", platforms):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        yield mock_config_entry
