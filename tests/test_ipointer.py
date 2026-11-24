"""Tests for the optional iPointer battery source."""

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.chery_connect.api import parse_ev_tile
from custom_components.chery_connect.const import (
    ACTIVE_SCAN_INTERVAL,
    API_BASE_URL,
    CONF_IPOINTER_REFRESH_TOKEN,
    CONF_IPOINTER_TOKEN,
    DOMAIN,
    IPOINTER_API_BASE_URL,
    ISSUE_IPOINTER_AUTH,
)
from custom_components.chery_connect.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .const import CHARGING, ELECTRIC_ENTITY_IDS, PLACEHOLDER_ELECTRIC_FIELDS, TOKEN

IPOINTER_TOKEN = "i" * 32
IPOINTER_REFRESH = "r" * 32
RENEWED_TOKEN = "w" * 32
IPOINTER_VEHICLE_INFO = f"{IPOINTER_API_BASE_URL}VehicleInfo"
IPOINTER_REFRESH_URL = f"{IPOINTER_API_BASE_URL}refresh-token"

# The battery tile as the iPointer app showed it on 2026-11-24 (values
# rounded): charging at 38 % with 34 km of electric range.
TILE = {
    "electric_State_OF_Charge": 38,
    "electric_State_OF_Charge_Text": "34km/38%",
    "electric_Cable_Charger_Status": 1,
    "EstChargeEndDsiplay": "3 שעות ו 28 דקות לסיום טעינה",
    "electric_Range_Vehicle_in_KM": 34,
    "regenerative": 0,
}


def _ipointer_info(tile: Any = None) -> dict[str, Any]:
    """Return an iPointer VehicleInfo with the tile as the JSON string it sends."""
    return {"EVTile": json.dumps([TILE if tile is None else tile])}


@pytest.fixture
def ipointer_entry(mock_config_entry: MockConfigEntry) -> MockConfigEntry:
    """Return an entry with iPointer connected."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data={
            **mock_config_entry.data,
            CONF_IPOINTER_TOKEN: IPOINTER_TOKEN,
            CONF_IPOINTER_REFRESH_TOKEN: IPOINTER_REFRESH,
        },
    )


async def _setup(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Set up a placeholder-sending car (Tiggo 8 PHEV)."""
    aioclient_mock.get(f"{API_BASE_URL}TestToken", json={})
    aioclient_mock.post(
        f"{API_BASE_URL}VehicleInfo",
        json=dict(vehicle_info, **PLACEHOLDER_ELECTRIC_FIELDS),
    )
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _bearers(aioclient_mock: AiohttpClientMocker, url: str) -> list[str]:
    """Return the Authorization header of every call to ``url``."""
    return [
        headers["Authorization"]
        for _, call_url, _, headers in aioclient_mock.mock_calls
        if str(call_url) == url
    ]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param({"EVTile": json.dumps([TILE])}, TILE, id="json_string"),
        pytest.param({"EVTile": [TILE]}, TILE, id="decoded_list"),
        pytest.param({"EVTile": TILE}, TILE, id="decoded_object"),
        pytest.param({"EVTile": "[]"}, None, id="empty_list"),
        pytest.param({"EVTile": "not json"}, None, id="invalid_json"),
        pytest.param({"EVTile": None}, None, id="null"),
        pytest.param({}, None, id="missing"),
    ],
)
def test_parse_ev_tile(payload: dict[str, Any], expected: Any) -> None:
    """The tile is read like the app reads it; anything else is None."""
    assert parse_ev_tile(payload) == expected


async def test_battery_from_ipointer(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """The real iPointer values replace the Chery placeholders."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, json=_ipointer_info())
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)

    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "38.0"
    assert hass.states.get("sensor.chery_tiggo_8_pro_electric_range").state == "34.0"
    assert hass.states.get(CHARGING).state == "on"
    status = hass.states.get("sensor.chery_tiggo_8_pro_charge_status")
    assert status.state == TILE["EstChargeEndDsiplay"]
    assert _bearers(aioclient_mock, IPOINTER_VEHICLE_INFO) == [
        f"Bearer {IPOINTER_TOKEN}"
    ]
    # Charging counts as active, so the car is polled every minute.
    assert ipointer_entry.runtime_data.update_interval == ACTIVE_SCAN_INTERVAL


async def test_ipointer_failure_hides_placeholders(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """An iPointer outage neither fails setup nor shows the Chery values."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, status=500)
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)

    assert ipointer_entry.runtime_data.last_update_success
    for entity_id in ELECTRIC_ENTITY_IDS:
        state = hass.states.get(entity_id)
        assert state is None or state.state == "unknown", entity_id
    assert not ir.async_get(hass).issues


async def test_rejected_token_renewed(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A rejected token is renewed with the refresh token sent as the Bearer."""
    calls: list[int] = []

    async def _vehicle_info(
        method: str, url: Any, data: Any
    ) -> AiohttpClientMockResponse:
        calls.append(1)
        if len(calls) == 1:
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(method, url, json=_ipointer_info())

    aioclient_mock.post(IPOINTER_VEHICLE_INFO, side_effect=_vehicle_info)
    aioclient_mock.post(IPOINTER_REFRESH_URL, json={"token": RENEWED_TOKEN})
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)

    assert _bearers(aioclient_mock, IPOINTER_REFRESH_URL) == [
        f"Bearer {IPOINTER_REFRESH}"
    ]
    assert _bearers(aioclient_mock, IPOINTER_VEHICLE_INFO) == [
        f"Bearer {IPOINTER_TOKEN}",
        f"Bearer {RENEWED_TOKEN}",
    ]
    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "38.0"
    assert not ir.async_get(hass).issues


async def test_dead_login_raises_repair_issue(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """When the refresh fails too, a repair issue asks to connect again."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, status=401)
    aioclient_mock.post(IPOINTER_REFRESH_URL, status=401)
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)

    assert ipointer_entry.runtime_data.last_update_success
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"{ISSUE_IPOINTER_AUTH}_{ipointer_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == ISSUE_IPOINTER_AUTH

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        f"{API_BASE_URL}VehicleInfo",
        json=dict(vehicle_info, **PLACEHOLDER_ELECTRIC_FIELDS),
    )
    aioclient_mock.post(f"{API_BASE_URL}lastLocation", json=last_location)
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, json=_ipointer_info())
    await ipointer_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert not ir.async_get(hass).issues
    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "38.0"


async def test_diagnostics_redacts_ipointer_tokens(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Neither iPointer token leaves the diagnostics."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, json=_ipointer_info())
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)

    dumped = json.dumps(await async_get_config_entry_diagnostics(hass, ipointer_entry))

    assert IPOINTER_TOKEN not in dumped
    assert IPOINTER_REFRESH not in dumped
    assert '"ev_source": "ipointer"' in dumped


async def test_dead_login_warns_once(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A login that stays dead logs one warning, not one per refresh."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, status=401)
    aioclient_mock.post(IPOINTER_REFRESH_URL, status=401)
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)
    await ipointer_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert caplog.text.count("iPointer rejected the login") == 1


async def test_disconnect_clears_issue(
    hass: HomeAssistant,
    ipointer_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Removing the iPointer login also removes its repair issue."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, status=401)
    aioclient_mock.post(IPOINTER_REFRESH_URL, status=401)
    await _setup(hass, ipointer_entry, aioclient_mock, vehicle_info, last_location)
    assert ir.async_get(hass).issues

    data = dict(ipointer_entry.data)
    data.pop(CONF_IPOINTER_TOKEN)
    data.pop(CONF_IPOINTER_REFRESH_TOKEN)
    hass.config_entries.async_update_entry(ipointer_entry, data=data)
    await hass.async_block_till_done()

    assert not ir.async_get(hass).issues


async def test_chery_login_accepted_by_ipointer(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Without an iPointer login, the Chery login brings the battery data."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, json=_ipointer_info())
    await _setup(hass, mock_config_entry, aioclient_mock, vehicle_info, last_location)

    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "38.0"
    assert hass.states.get(CHARGING).state == "on"
    assert _bearers(aioclient_mock, IPOINTER_VEHICLE_INFO) == [f"Bearer {TOKEN}"]
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["ev_login"] == "chery_login_ok"


async def test_chery_login_rejected_by_ipointer(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A rejected Chery login is tried once, with no repair issue or entities."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, status=401)
    await _setup(hass, mock_config_entry, aioclient_mock, vehicle_info, last_location)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert mock_config_entry.runtime_data.last_update_success
    assert len(_bearers(aioclient_mock, IPOINTER_VEHICLE_INFO)) == 1
    assert not ir.async_get(hass).issues
    for entity_id in ELECTRIC_ENTITY_IDS:
        assert hass.states.get(entity_id) is None, entity_id
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["ev_login"] == "chery_login_rejected"


async def test_chery_login_without_battery_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """No tile yet leaves the Chery data alone and keeps trying."""
    aioclient_mock.post(IPOINTER_VEHICLE_INFO, json={})
    await _setup(hass, mock_config_entry, aioclient_mock, vehicle_info, last_location)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(_bearers(aioclient_mock, IPOINTER_VEHICLE_INFO)) == 2
    for entity_id in ELECTRIC_ENTITY_IDS:
        assert hass.states.get(entity_id) is None, entity_id
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["ev_login"] == "chery_login_no_battery_data"


async def test_chery_login_failure_after_data_shows_unknown(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """Once the battery data came, a later failure shows unknown."""
    answers = [_ipointer_info(), None]

    async def _vehicle_info(method: str, url: Any, data: Any) -> Any:
        if (payload := answers.pop(0)) is None:
            return AiohttpClientMockResponse(method, url, status=500)
        return AiohttpClientMockResponse(method, url, json=payload)

    aioclient_mock.post(IPOINTER_VEHICLE_INFO, side_effect=_vehicle_info)
    await _setup(hass, mock_config_entry, aioclient_mock, vehicle_info, last_location)
    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "38.0"

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "unknown"


async def test_chery_login_rejected_after_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    vehicle_info: dict[str, Any],
    last_location: dict[str, Any],
) -> None:
    """A later rejection shows unknown and is reported in diagnostics."""
    answers = [_ipointer_info(), None]

    async def _vehicle_info(method: str, url: Any, data: Any) -> Any:
        if (payload := answers.pop(0)) is None:
            return AiohttpClientMockResponse(method, url, status=401)
        return AiohttpClientMockResponse(method, url, json=payload)

    aioclient_mock.post(IPOINTER_VEHICLE_INFO, side_effect=_vehicle_info)
    await _setup(hass, mock_config_entry, aioclient_mock, vehicle_info, last_location)
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.chery_tiggo_8_pro_ev_battery").state == "unknown"
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["ev_login"] == "chery_login_rejected"
