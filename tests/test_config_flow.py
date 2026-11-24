"""Tests for the Chery Connect config, reauth and options flows."""

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    API_BASE_URL,
    CONF_CODE,
    CONF_MOBILE_PHONE,
    CONF_RESEND,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DOMAIN,
)

from .const import CODE, NEW_TOKEN, OTHER_V_NUMBER, PHONE, TOKEN, V_NUMBER

OTP_URL = f"{API_BASE_URL}login/otp"
OTP_CHECK_URL = f"{API_BASE_URL}login/otpCheck"
USER_INPUT = {CONF_MOBILE_PHONE: PHONE, CONF_V_NUMBER: V_NUMBER}


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep flow tests from setting up the integration.

    A finished flow (create or reauth reload) would otherwise set up the
    platforms in the background, racing the test teardown and leaving the
    legacy device_tracker timer behind.
    """
    with patch(
        "custom_components.chery_connect.async_setup_entry", return_value=True
    ) as mock:
        yield mock


def _mock_login(aioclient_mock: AiohttpClientMocker, token: str = NEW_TOKEN) -> None:
    """Answer the OTP request and the code check successfully."""
    aioclient_mock.post(OTP_URL, json={"rescode": 1})
    aioclient_mock.post(OTP_CHECK_URL, json={"token": token})


def _otp_requests(aioclient_mock: AiohttpClientMocker) -> list[Any]:
    """Return the bodies of every SMS request sent so far."""
    return [
        body for _, url, body, _ in aioclient_mock.mock_calls if str(url) == OTP_URL
    ]


async def _start_user_flow(hass: HomeAssistant, user_input: dict[str, str]) -> Any:
    """Open the user flow and submit step 1."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


@pytest.mark.parametrize(
    ("phone", "v_number"),
    [
        pytest.param(PHONE, V_NUMBER, id="plain"),
        pytest.param("+972-50-123-4567", "12-345-67", id="formatted"),
        pytest.param(" 050-1234567 ", " 1234567 ", id="padded"),
    ],
)
async def test_user_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, phone: str, v_number: str
) -> None:
    """Phone and plate are normalised; the code becomes the stored token."""
    _mock_login(aioclient_mock)
    result = await _start_user_flow(
        hass, {CONF_MOBILE_PHONE: phone, CONF_V_NUMBER: v_number}
    )
    assert result["step_id"] == "otp"
    assert _otp_requests(aioclient_mock)[0]["MobilePhone"] == PHONE

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: CODE}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == V_NUMBER
    assert result["title"] == "Chery ••••567"
    assert result["data"] == {
        CONF_MOBILE_PHONE: PHONE,
        CONF_V_NUMBER: V_NUMBER,
        CONF_TOKEN: NEW_TOKEN,
    }


@pytest.mark.parametrize(
    ("phone", "v_number", "errors"),
    [
        pytest.param(
            "---", V_NUMBER, {CONF_MOBILE_PHONE: "invalid_phone"}, id="phone_no_digits"
        ),
        pytest.param(
            "050-123456a",
            V_NUMBER,
            {CONF_MOBILE_PHONE: "invalid_phone"},
            id="phone_letter",
        ),
        pytest.param(
            "050 1234567",
            V_NUMBER,
            {CONF_MOBILE_PHONE: "invalid_phone"},
            id="phone_space",
        ),
        pytest.param(
            "05+01234567",
            V_NUMBER,
            {CONF_MOBILE_PHONE: "invalid_phone"},
            id="phone_inner_plus",
        ),
        pytest.param(
            PHONE, "12-345-AB", {CONF_V_NUMBER: "invalid_v_number"}, id="plate_letters"
        ),
        pytest.param(
            PHONE, "12 345 67", {CONF_V_NUMBER: "invalid_v_number"}, id="plate_space"
        ),
        pytest.param(
            PHONE, "+1234567", {CONF_V_NUMBER: "invalid_v_number"}, id="plate_plus"
        ),
        pytest.param(
            PHONE, "--", {CONF_V_NUMBER: "invalid_v_number"}, id="plate_no_digits"
        ),
        pytest.param(
            "abc",
            "xyz",
            {CONF_MOBILE_PHONE: "invalid_phone", CONF_V_NUMBER: "invalid_v_number"},
            id="both",
        ),
    ],
)
async def test_user_flow_rejects_invalid_characters(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    phone: str,
    v_number: str,
    errors: dict[str, str],
) -> None:
    """Only digits and dashes are accepted; the bad field is flagged, no SMS sent."""
    result = await _start_user_flow(
        hass, {CONF_MOBILE_PHONE: phone, CONF_V_NUMBER: v_number}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == errors
    assert not _otp_requests(aioclient_mock)


async def test_user_flow_recovers_after_invalid_input(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Fixing the field after the error continues to the SMS step."""
    _mock_login(aioclient_mock)
    result = await _start_user_flow(
        hass, {CONF_MOBILE_PHONE: PHONE, CONF_V_NUMBER: "12-345-6X"}
    )
    assert result["errors"] == {CONF_V_NUMBER: "invalid_v_number"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["step_id"] == "otp"
    assert _otp_requests(aioclient_mock)[0]["VNumber"] == V_NUMBER


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """The same plate typed with dashes is detected as a duplicate."""
    mock_config_entry.add_to_hass(hass)
    result = await _start_user_flow(
        hass, {CONF_MOBILE_PHONE: PHONE, CONF_V_NUMBER: "12-345-67"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert not _otp_requests(aioclient_mock)


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        pytest.param({"json": {"rescode": -2}}, "blocked", id="blocked"),
        pytest.param({"status": 500}, "cannot_connect", id="server_error"),
        pytest.param({"exc": TimeoutError}, "cannot_connect", id="timeout"),
        pytest.param({"exc": RuntimeError}, "unknown", id="unexpected"),
    ],
)
async def test_user_flow_otp_request_errors_recover(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, Any],
    error: str,
) -> None:
    """A failed SMS request keeps the form filled in and can be retried."""
    aioclient_mock.post(OTP_URL, **kwargs)
    result = await _start_user_flow(hass, USER_INPUT)
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    _mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["step_id"] == "otp"


@pytest.mark.parametrize(
    ("user_input", "kwargs", "error"),
    [
        pytest.param(
            {CONF_CODE: CODE}, {"json": {"token": ""}}, "invalid_otp", id="bad_code"
        ),
        pytest.param({CONF_CODE: "  "}, {"json": {}}, "invalid_otp", id="empty_code"),
        pytest.param(
            {CONF_CODE: CODE}, {"status": 503}, "cannot_connect", id="server_error"
        ),
        pytest.param(
            {CONF_CODE: CODE}, {"exc": RuntimeError}, "unknown", id="unexpected"
        ),
    ],
)
async def test_otp_errors_recover(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    user_input: dict[str, str],
    kwargs: dict[str, Any],
    error: str,
) -> None:
    """A rejected or failed code check stays on the code step."""
    aioclient_mock.post(OTP_URL, json={"rescode": 1})
    aioclient_mock.post(OTP_CHECK_URL, **kwargs)
    result = await _start_user_flow(hass, USER_INPUT)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["step_id"] == "otp"
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    _mock_login(aioclient_mock)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("kwargs", "errors"),
    [
        pytest.param({"json": {"rescode": 1}}, {}, id="sent"),
        pytest.param({"status": 500}, {"base": "cannot_connect"}, id="failed"),
    ],
)
async def test_otp_resend(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    kwargs: dict[str, Any],
    errors: dict[str, str],
) -> None:
    """Ticking resend sends a new SMS for the same phone and stays on the step."""
    aioclient_mock.post(OTP_URL, json={"rescode": 1})
    result = await _start_user_flow(hass, USER_INPUT)
    aioclient_mock.clear_requests()
    aioclient_mock.post(OTP_URL, **kwargs)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_RESEND: True}
    )

    assert result["step_id"] == "otp"
    assert result["errors"] == errors
    assert _otp_requests(aioclient_mock)[0]["MobilePhone"] == PHONE


async def test_reauth_confirms_before_sms(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Reauth waits for a click, keeps phone and plate, replaces only the token."""
    mock_config_entry.add_to_hass(hass)
    _mock_login(aioclient_mock)
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(f"{API_BASE_URL}VehicleInfo", json={})
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json={})

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"][CONF_V_NUMBER] == V_NUMBER
    assert not _otp_requests(aioclient_mock)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "otp"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: CODE}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data == {
        CONF_MOBILE_PHONE: PHONE,
        CONF_V_NUMBER: V_NUMBER,
        CONF_TOKEN: NEW_TOKEN,
    }


async def test_reauth_sms_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A failed SMS during reauth stays on the confirm step; no vehicle form."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.post(OTP_URL, json={"rescode": -2})
    result = await mock_config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "blocked"}
    assert mock_config_entry.data[CONF_TOKEN] == TOKEN


async def test_reauth_unique_id_mismatch(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An entry whose stored plate no longer matches its id is not overwritten."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=V_NUMBER,
        data={
            CONF_MOBILE_PHONE: PHONE,
            CONF_V_NUMBER: OTHER_V_NUMBER,
            CONF_TOKEN: TOKEN,
        },
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"
    assert not _otp_requests(aioclient_mock)


async def test_options_flow(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The scan interval option is stored; the form defaults to the current one."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_SCAN_INTERVAL: 15}
    )
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {CONF_SCAN_INTERVAL: 30}
