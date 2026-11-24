"""Tests for the extra endpoints: parsers, cadence, failure isolation, alerts."""

import json
from datetime import timedelta
from typing import Any

import pytest
from aiohttp import ClientError
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.chery_connect.const import (
    API_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    ENDPOINT_HISTORY,
    ENDPOINT_MESSAGES,
    ENDPOINT_MY_CAR,
    EVENT_DRIVER_ALERT,
    EXTRA_DISTANCE_MONTH,
    EXTRA_DISTANCE_MONTH_AVG,
    EXTRA_DISTANCE_TODAY,
    EXTRAS_REFRESH_INTERVAL,
)
from custom_components.chery_connect.extras import (
    describe_shape,
    parse_distance,
    parse_driver_alerts,
    parse_messages,
    parse_trip,
)
from custom_components.chery_connect.sensor import (
    _messages_attrs,
    _messages_count,
    _trip_attrs,
    _trip_end,
)

from .const import EXTRA_DISTANCE, EXTRA_DRIVER_ALERTS

PREFIX = "chery_tiggo_8_pro"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {
                "DisanceMeterToday": "7",
                "DistanceKMMonth": json.dumps([{"DATEKEY": "1", "DistanceKMMonth": 9}]),
                "DistanceKMMonthAVG": "4.5",
            },
            (7.0, 9.0, 4.5),
            id="json_strings",
        ),
        pytest.param(
            {"DistanceKMMonth": [{"DATEKEY": "1", "DistanceKMMonth": "3"}]},
            (None, 3.0, None),
            id="already_decoded",
        ),
        pytest.param(
            {"DistanceKMMonth": json.dumps([{"DistanceKMMonth": 5}])},
            (None, None, None),
            id="first_month_undated",
        ),
        pytest.param(
            {"DistanceKMMonth": "{not json", "DistanceKMMonthAVG": ""},
            (None, None, None),
            id="bad_json",
        ),
        pytest.param({}, (None, None, None), id="empty"),
    ],
)
def test_parse_distance(payload: dict[str, Any], expected: tuple[Any, ...]) -> None:
    """Distance fields decode JSON strings and tolerate odd shapes."""
    parsed = parse_distance(payload)
    assert (
        parsed[EXTRA_DISTANCE_TODAY],
        parsed[EXTRA_DISTANCE_MONTH],
        parsed[EXTRA_DISTANCE_MONTH_AVG],
    ) == expected


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        pytest.param("", [], id="empty_string"),
        pytest.param("{bad", [], id="bad_json"),
        pytest.param(
            json.dumps(
                [
                    {
                        "SentenceDesc": " Speeding ",
                        "GMUUTCDatetime": "2026-11-23T08:00:00",
                    },
                    {"SentenceDesc": "", "GMUUTCDatetime": "nonsense"},
                    "not an alert",
                ]
            ),
            [
                {"message": "Speeding", "time": "2026-11-23T08:00:00+00:00"},
                {"message": None, "time": None},
            ],
            id="naive_time_is_utc",
        ),
        pytest.param(
            [{"SentenceDesc": "Harsh", "GMUUTCDatetime": "2026-11-23T10:00:00+02:00"}],
            [{"message": "Harsh", "time": "2026-11-23T10:00:00+02:00"}],
            id="decoded_with_offset",
        ),
    ],
)
def test_parse_driver_alerts(report: Any, expected: list[dict[str, Any]]) -> None:
    """DiagReport becomes a list of message/time alerts."""
    assert parse_driver_alerts({"DiagReport": report}) == expected


def test_parse_trip_and_messages_edge_cases() -> None:
    """Empty or odd trip and message payloads map to safe values."""
    assert parse_trip({}) is None
    assert parse_trip({"root": []}) is None
    assert parse_trip({"root": [{"G": "bad"}, "x"]}) == {
        "points": 2,
        "start": None,
        "end": None,
    }
    assert parse_messages({"Messages": "none"}) == {
        "count": 0,
        "latest_title": None,
        "latest_text": None,
        "latest_time": None,
    }


def test_describe_shape_hides_values() -> None:
    """The debug shape lists types and lengths, never the values."""
    shape = describe_shape({"root": [1, 2], "Messagetext": "secret", "count": 3})
    assert shape == {"root": "list[2]", "Messagetext": "str[6]", "count": "int"}
    assert "secret" not in str(shape)


def _extras_calls(aioclient_mock: AiohttpClientMocker) -> int:
    endpoints = {ENDPOINT_MY_CAR, ENDPOINT_HISTORY, ENDPOINT_MESSAGES}
    return sum(
        1
        for _method, url, _data, _headers in aioclient_mock.mock_calls
        if str(url).removeprefix(API_BASE_URL) in endpoints
    )


async def _tick(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_extras_entities(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Trip and message sensors carry their small attribute sets."""
    trip = hass.states.get(f"sensor.{PREFIX}_last_trip")
    assert trip.attributes["start"] == "2026-11-23T09:00:00+02:00"
    assert trip.attributes["points"] == 3
    messages = hass.states.get(f"sensor.{PREFIX}_messages")
    assert messages.attributes["latest_title"] == "Recall notice"
    assert messages.attributes["latest_time"] == "2026-11-22T09:30:00+02:00"


async def test_extras_slow_cadence(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Extras are fetched at setup, skipped on normal polls, refetched when due."""
    assert _extras_calls(aioclient_mock) == 4

    await _tick(hass, freezer, DEFAULT_SCAN_INTERVAL)
    assert _extras_calls(aioclient_mock) == 4

    await _tick(hass, freezer, EXTRAS_REFRESH_INTERVAL)
    assert _extras_calls(aioclient_mock) == 8


@pytest.mark.parametrize(
    ("failing", "missing_entity"),
    [
        pytest.param(EXTRA_DISTANCE, "distance_today", id="distance"),
        pytest.param(ENDPOINT_HISTORY, "last_trip", id="history"),
        pytest.param(ENDPOINT_MESSAGES, "messages", id="messages"),
        pytest.param(EXTRA_DRIVER_ALERTS, None, id="driver_alerts"),
    ],
)
async def test_extra_failure_is_isolated(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_api: AiohttpClientMocker,
    mock_extras: dict[str, Any],
    failing: str,
    missing_entity: str | None,
) -> None:
    """A failing extra endpoint loses only its own entity, never the setup."""
    mock_extras[failing] = ClientError("boom")
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(f"sensor.{PREFIX}_odometer").state == "12345.0"
    assert hass.states.get(f"event.{PREFIX}_driver_alert") is not None
    if missing_entity:
        assert hass.states.get(f"sensor.{PREFIX}_{missing_entity}") is None


async def test_extra_failure_keeps_last_value(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_extras: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """A later failure keeps the previous value instead of going unknown."""
    mock_extras[EXTRA_DISTANCE] = ClientError("boom")
    await _tick(hass, freezer, EXTRAS_REFRESH_INTERVAL)
    assert hass.states.get(f"sensor.{PREFIX}_distance_today").state == "12.5"


async def test_driver_alerts_fire_once(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_extras: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """Only alerts new since the last report fire, once each, also on the entity."""
    events: list[Event] = async_capture_events(hass, EVENT_DRIVER_ALERT)
    event_entity = f"event.{PREFIX}_driver_alert"
    assert hass.states.get(event_entity).state == "unknown"

    report = json.loads(mock_extras[EXTRA_DRIVER_ALERTS]["DiagReport"])
    report.append({"SentenceDesc": "Speeding", "GMUUTCDatetime": "2026-11-23T09:00:00"})
    mock_extras[EXTRA_DRIVER_ALERTS] = {"DiagReport": json.dumps(report)}
    await _tick(hass, freezer, EXTRAS_REFRESH_INTERVAL)

    assert [event.data["message"] for event in events] == ["Speeding"]
    assert events[0].data["config_entry_id"] == init_integration.entry_id
    assert events[0].data["time"] == "2026-11-23T09:00:00+00:00"
    state = hass.states.get(event_entity)
    assert state.state != "unknown"
    assert state.attributes["event_type"] == "driver_alert"
    assert state.attributes["message"] == "Speeding"

    await _tick(hass, freezer, EXTRAS_REFRESH_INTERVAL)
    assert len(events) == 1


async def test_trip_goes_unknown_when_history_empties(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_extras: dict[str, Any],
    freezer: FrozenDateTimeFactory,
) -> None:
    """An empty trace later on means no trip: unknown, no stale attributes."""
    mock_extras[ENDPOINT_HISTORY] = {"root": []}
    await _tick(hass, freezer, EXTRAS_REFRESH_INTERVAL)
    trip = hass.states.get(f"sensor.{PREFIX}_last_trip")
    assert trip.state == "unknown"
    assert "points" not in trip.attributes


@pytest.mark.parametrize("value", [None, "text", 3])
def test_extras_value_helpers_tolerate_non_dicts(value: Any) -> None:
    """Sensor helpers for dict-valued extras return empty results otherwise."""
    assert _messages_count(value) is None
    assert _messages_attrs(value) == {}
    assert _trip_end(value) is None
    assert _trip_attrs(value) == {}
