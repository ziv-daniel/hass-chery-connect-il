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
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.chery_connect.const import (
    API_BASE_URL,
    CONF_MOBILE_PHONE,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DOMAIN,
    ENDPOINT_HISTORY,
    ENDPOINT_MESSAGES,
    ENDPOINT_MY_CAR,
    MY_CAR_TAB_DISTANCE,
    MY_CAR_TAB_DRIVER_ALERTS,
    MY_CAR_TAB_DRIVING_EVENTS,
)

from .const import (
    EXTRA_DISTANCE,
    EXTRA_DRIVER_ALERTS,
    EXTRA_DRIVING_EVENTS,
    PHONE,
    TOKEN,
    V_NUMBER,
)


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
def extras_payloads() -> dict[str, Any]:
    """Payloads for the extra endpoints; a test may swap one for an exception."""
    return {
        EXTRA_DISTANCE: load_json_object_fixture("my_car_distance.json"),
        EXTRA_DRIVER_ALERTS: load_json_object_fixture("my_car_driver_alerts.json"),
        EXTRA_DRIVING_EVENTS: load_json_object_fixture("my_car_driving_events.json"),
        ENDPOINT_HISTORY: load_json_object_fixture("history.json"),
        ENDPOINT_MESSAGES: load_json_object_fixture("messages.json"),
    }


def register_extras(
    aioclient_mock: AiohttpClientMocker, payloads: dict[str, Any]
) -> None:
    """Answer myCar, getHistory and getMessages from ``payloads`` at call time."""

    def _answer(name: str, url: URL) -> AiohttpClientMockResponse:
        payload = payloads[name]
        if isinstance(payload, BaseException):
            return AiohttpClientMockResponse("post", url, exc=payload)
        return AiohttpClientMockResponse("post", url, json=payload)

    async def _my_car(method: str, url: URL, data: Any) -> AiohttpClientMockResponse:
        tabs = {MY_CAR_TAB_DISTANCE: EXTRA_DISTANCE}
        tabs[MY_CAR_TAB_DRIVER_ALERTS] = EXTRA_DRIVER_ALERTS
        tabs[MY_CAR_TAB_DRIVING_EVENTS] = EXTRA_DRIVING_EVENTS
        return _answer(tabs[data["tabId"]], url)

    def _plain(name: str):
        async def _side_effect(
            method: str, url: URL, data: Any
        ) -> AiohttpClientMockResponse:
            return _answer(name, url)

        return _side_effect

    aioclient_mock.post(f"{API_BASE_URL}{ENDPOINT_MY_CAR}", side_effect=_my_car)
    for endpoint in (ENDPOINT_HISTORY, ENDPOINT_MESSAGES):
        aioclient_mock.post(f"{API_BASE_URL}{endpoint}", side_effect=_plain(endpoint))


@pytest.fixture(autouse=True)
def mock_extras(
    aioclient_mock: AiohttpClientMocker, extras_payloads: dict[str, Any]
) -> dict[str, Any]:
    """Register the extra endpoints for every test."""
    register_extras(aioclient_mock, extras_payloads)
    return extras_payloads


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
    return ["sensor", "binary_sensor", "device_tracker", "event"]


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
