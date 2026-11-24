"""Slow-changing extras: distance, driver alerts, trip history and messages.

These come from the app's personal-zone endpoints (myCar, getHistory,
getMessages). Their payload shapes are taken from the app's JavaScript,
not from a live capture, so every parser tolerates missing or odd fields,
and a failing endpoint never fails the main VehicleInfo refresh.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .api import CheryApiError, CheryConnectApiClient, parse_api_time, parse_float
from .const import (
    EXTRA_DISTANCE_MONTH,
    EXTRA_DISTANCE_MONTH_AVG,
    EXTRA_DISTANCE_TODAY,
    EXTRA_MESSAGES,
    EXTRA_TRIP,
    EXTRAS_REFRESH_INTERVAL,
    MY_CAR_TAB_DISTANCE,
    MY_CAR_TAB_DRIVER_ALERTS,
)

_LOGGER = logging.getLogger(__name__)

type DriverAlert = dict[str, str | None]


def _json_field(value: Any) -> Any:
    """Decode a field the API sends as a JSON string; pass decoded values through."""
    if not isinstance(value, str):
        return value
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def describe_shape(payload: dict[str, Any]) -> dict[str, str]:
    """Describe each field's type (and length) without logging any value."""
    shape: dict[str, str] = {}
    for key, value in payload.items():
        kind = type(value).__name__
        shape[key] = f"{kind}[{len(value)}]" if isinstance(value, list | str) else kind
    return shape


def parse_distance(payload: dict[str, Any]) -> dict[str, float | None]:
    """Distance today, this month and the monthly average (km), from myCar tab 0.

    The app treats the first DistanceKMMonth entry that has a DATEKEY as
    the current month (it labels entry n as "now minus n months").
    """
    months = _json_field(payload.get("DistanceKMMonth"))
    current = None
    if isinstance(months, list) and months:
        first = months[0]
        if isinstance(first, dict) and first.get("DATEKEY"):
            current = parse_float(first.get("DistanceKMMonth"))
    return {
        EXTRA_DISTANCE_TODAY: parse_float(payload.get("DisanceMeterToday")),
        EXTRA_DISTANCE_MONTH: current,
        EXTRA_DISTANCE_MONTH_AVG: parse_float(
            _json_field(payload.get("DistanceKMMonthAVG"))
        ),
    }


def _alert_time(value: Any) -> datetime | None:
    """GMUUTCDatetime is UTC even when it carries no offset."""
    if not isinstance(value, str) or (parsed := dt_util.parse_datetime(value)) is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_driver_alerts(payload: dict[str, Any]) -> list[DriverAlert]:
    """Driver-behaviour alerts from myCar tab 2 (DiagReport, a JSON string)."""
    report = _json_field(payload.get("DiagReport"))
    if not isinstance(report, list):
        return []
    return [
        {
            "message": str(item.get("SentenceDesc") or "").strip() or None,
            "time": _iso(_alert_time(item.get("GMUUTCDatetime"))),
        }
        for item in report
        if isinstance(item, dict)
    ]


def parse_trip(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Summarise the trip trace (root = points with an API-local time "G").

    Only the point count and the first/last times are kept: the full trace
    holds hundreds of coordinates, too much for state attributes.
    """
    points = payload.get("root")
    if not isinstance(points, list) or not points:
        return None
    times = [
        parsed
        for point in points
        if isinstance(point, dict) and (parsed := parse_api_time(point.get("G")))
    ]
    return {
        "points": len(points),
        "start": _iso(min(times)) if times else None,
        "end": _iso(max(times)) if times else None,
    }


def parse_messages(payload: dict[str, Any]) -> dict[str, Any]:
    """Message count and the newest message (the app shows none when absent)."""
    messages = payload.get("Messages")
    if not isinstance(messages, list):
        messages = []
    items = [item for item in messages if isinstance(item, dict)]
    latest = max(items, key=lambda item: str(item.get("DateTime") or ""), default={})
    return {
        "count": len(items),
        "latest_title": latest.get("Messagetitle"),
        "latest_text": latest.get("Messagetext"),
        "latest_time": _iso(parse_api_time(latest.get("DateTime"))),
    }


class CheryExtras:
    """Fetch the extra endpoints on a slow cadence and keep the last values."""

    def __init__(self, api: CheryConnectApiClient) -> None:
        """Initialize with no values; the first refresh fetches everything."""
        self._api = api
        self._values: dict[str, Any] = {}
        self._seen_alerts: set[tuple[str | None, str | None]] | None = None
        self._last_fetch: datetime | None = None

    def _is_due(self) -> bool:
        if self._last_fetch is None:
            return True
        return dt_util.utcnow() - self._last_fetch >= EXTRAS_REFRESH_INTERVAL

    async def async_refresh(self) -> tuple[dict[str, Any], list[DriverAlert]]:
        """Return (values, driver alerts new since the last fetch)."""
        if not self._is_due():
            return dict(self._values), []
        self._last_fetch = dt_util.utcnow()
        api = self._api
        distance = await self._fetch(
            "myCar distance", lambda: api.get_my_car(MY_CAR_TAB_DISTANCE)
        )
        if distance is not None:
            self._values.update(parse_distance(distance))
        if (trip := await self._fetch("getHistory", api.get_history)) is not None:
            self._values[EXTRA_TRIP] = parse_trip(trip)
        if (messages := await self._fetch("getMessages", api.get_messages)) is not None:
            self._values[EXTRA_MESSAGES] = parse_messages(messages)
        alerts = await self._fetch(
            "myCar driver alerts", lambda: api.get_my_car(MY_CAR_TAB_DRIVER_ALERTS)
        )
        new_alerts = (
            [] if alerts is None else self._new_alerts(parse_driver_alerts(alerts))
        )
        return dict(self._values), new_alerts

    async def _fetch(
        self, name: str, request: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any] | None:
        """Call one endpoint; on failure keep the last values and return None."""
        try:
            payload = await request()
        except CheryApiError as err:
            _LOGGER.debug("Extra %s unavailable, keeping last value: %s", name, err)
            return None
        _LOGGER.debug("Extra %s response shape: %s", name, describe_shape(payload))
        return payload

    def _new_alerts(self, alerts: list[DriverAlert]) -> list[DriverAlert]:
        """Return alerts not seen in the previous report (none on the first)."""
        keys = {(alert["time"], alert["message"]) for alert in alerts}
        previous, self._seen_alerts = self._seen_alerts, keys
        if previous is None:
            return []
        return [a for a in alerts if (a["time"], a["message"]) not in previous]
