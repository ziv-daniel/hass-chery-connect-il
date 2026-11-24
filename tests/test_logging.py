"""Every API call, refresh and setup is logged at debug, without secrets."""

import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.api import CheryApiError, CheryConnectApiClient
from custom_components.chery_connect.const import API_BASE_URL

from .const import CODE, NEW_TOKEN, PHONE, TOKEN, V_NUMBER

LOGGER = "custom_components.chery_connect"


def _secrets(*payloads: dict[str, Any]) -> list[str]:
    """Values that must never appear in a log line."""
    values = [TOKEN, NEW_TOKEN, PHONE, V_NUMBER, CODE]
    for payload in payloads:
        values += [
            str(payload[k])
            for k in ("Latitude", "Longitude", "Longtitude")
            if k in payload
        ]
    return values


async def test_setup_and_refresh_are_logged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setup logs the interval; each call logs endpoint, status and fields."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, title="Chery ••••567")
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    text = caplog.text
    assert "refreshing VehicleInfo + lastLocation every 0:10:00" in text
    assert "API call GET TestToken" in text
    assert "API GET TestToken: HTTP 200 in" in text
    assert "Scheduled refresh started (every 0:10:00" in text
    for endpoint in ("VehicleInfo", "lastLocation"):
        assert f"API call POST {endpoint}" in text
        assert f"API POST {endpoint}: HTTP 200 in" in text
    assert f"API POST VehicleInfo: {len(vehicle_info)} fields" in text
    refreshed = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and "refreshed (every 0:10:00)" in r.getMessage()
    ]
    assert len(refreshed) == 1
    assert f"{len(vehicle_info)} fields, position from" in refreshed[0].getMessage()
    for secret in _secrets(vehicle_info, last_location):
        assert secret not in text


async def test_login_calls_log_field_names_only(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The OTP calls log which fields were sent, never their values."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    aioclient_mock.post(f"{API_BASE_URL}login/otp", json={"rescode": 1})
    aioclient_mock.post(f"{API_BASE_URL}login/otpCheck", json={"token": NEW_TOKEN})
    client = CheryConnectApiClient(async_get_clientsession(hass))

    await client.request_otp(PHONE, V_NUMBER)
    await client.check_otp(PHONE, V_NUMBER, CODE)

    assert "request fields: ['MobilePhone', 'VNumber', 'appid']" in caplog.text
    assert "SMS code request answered rescode=1" in caplog.text
    for secret in _secrets():
        assert secret not in caplog.text


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        pytest.param({"exc": TimeoutError}, "failed after", id="timeout"),
        pytest.param({"status": 503}, "HTTP 503 in", id="http_error"),
        pytest.param({"text": "<html>"}, "response is not JSON", id="not_json"),
        pytest.param({"json": [1]}, "expected a JSON object, got list", id="list"),
    ],
)
async def test_failures_are_logged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    """Each kind of failed call leaves a debug line saying why."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", **kwargs)
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(CheryApiError):
        await client.get_vehicle_info()

    assert expected in caplog.text
    assert TOKEN not in caplog.text


async def test_token_check_failure_is_logged(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A network failure on TestToken is logged too."""
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    aioclient_mock.get(f"{API_BASE_URL}TestToken", exc=TimeoutError)
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(CheryApiError):
        await client.test_token()

    assert "API GET TestToken failed after" in caplog.text
