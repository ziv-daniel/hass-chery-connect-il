"""Tests for the Chery Connect API client."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.api import (
    BlockedError,
    CheryApiError,
    CheryConnectApiClient,
    InvalidAuthError,
    InvalidOtpError,
    parse_float,
    parse_odometer,
)
from custom_components.chery_connect.const import API_BASE_URL

TOKEN = "t" * 20


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("12,345", 12345.0, id="commas"),
        pytest.param("12345", 12345.0, id="plain"),
        pytest.param(12345, 12345.0, id="int"),
        pytest.param(" 88.5 ", 88.5, id="padded"),
        pytest.param(None, None, id="none"),
        pytest.param("", None, id="empty"),
        pytest.param("abc", None, id="text"),
    ],
)
def test_parse_float(value: object, expected: float | None) -> None:
    """Numbers arrive as strings with thousands separators."""
    assert parse_float(value) == expected
    assert parse_odometer(value) == expected


async def test_request_otp_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """login/otp posts phone, vehicle and appid without a token."""
    aioclient_mock.post(f"{API_BASE_URL}login/otp", json={"res": "ok", "rescode": 1})
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    payload = await client.request_otp("0500000000", "1234567")

    assert payload["rescode"] == 1
    _, _, body, headers = aioclient_mock.mock_calls[0]
    assert body == {"MobilePhone": "0500000000", "VNumber": "1234567", "appid": 34}
    assert "Authorization" not in headers


async def test_request_otp_blocked(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Rescode -2 means the server refused the login."""
    aioclient_mock.post(f"{API_BASE_URL}login/otp", json={"res": "no", "rescode": -2})
    client = CheryConnectApiClient(async_get_clientsession(hass))

    with pytest.raises(BlockedError):
        await client.request_otp("0500000000", "1234567")


async def test_check_otp_returns_token(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A long token is accepted and kept on the client."""
    aioclient_mock.post(f"{API_BASE_URL}login/otpCheck", json={"token": TOKEN})
    client = CheryConnectApiClient(async_get_clientsession(hass))

    assert await client.check_otp("0500000000", "1234567", "123456") == TOKEN
    assert client.token == TOKEN
    _, _, body, _ = aioclient_mock.mock_calls[0]
    assert body == {"MobilePhone": "0500000000", "VNumber": "1234567", "Code": "123456"}


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"token": "short"}, id="short"),
        pytest.param({"token": None}, id="null"),
        pytest.param({}, id="missing"),
    ],
)
async def test_check_otp_rejected(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, payload: dict
) -> None:
    """The app only accepts tokens longer than 10 characters."""
    aioclient_mock.post(f"{API_BASE_URL}login/otpCheck", json=payload)
    client = CheryConnectApiClient(async_get_clientsession(hass))

    with pytest.raises(InvalidOtpError):
        await client.check_otp("0500000000", "1234567", "123456")


async def test_bearer_header_and_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Data calls send the Bearer token and return the JSON body."""
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json={"Odometer": "1,000"})
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json={"Latitude": "32.1"})
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    assert await client.get_vehicle_info() == {"Odometer": "1,000"}
    assert await client.get_last_location() == {"Latitude": "32.1"}
    for call in aioclient_mock.mock_calls:
        assert call[3]["Authorization"] == f"Bearer {TOKEN}"


async def test_test_token_uses_get(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """TestToken is a GET."""
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    assert await client.test_token() is True
    assert aioclient_mock.mock_calls[0][0] == "GET"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        pytest.param(401, InvalidAuthError, id="401"),
        pytest.param(500, CheryApiError, id="500"),
    ],
)
async def test_http_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    status: int,
    error: type[Exception],
) -> None:
    """401 means a dead token; other statuses are API errors."""
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", status=status)
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(error):
        await client.get_vehicle_info()


async def test_timeout_is_api_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Network timeouts are wrapped in CheryApiError."""
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", exc=TimeoutError)
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(CheryApiError):
        await client.get_vehicle_info()


async def test_non_dict_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A JSON list instead of an object is rejected."""
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json=[1, 2])
    client = CheryConnectApiClient(async_get_clientsession(hass), TOKEN)

    with pytest.raises(CheryApiError):
        await client.get_vehicle_info()
