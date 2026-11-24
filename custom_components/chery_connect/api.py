"""Chery Connect API client.

Mirrors the Chery Connect v1.5.5 app. Auth is owner OTP: login/otp sends an SMS, then
login/otpCheck returns a Bearer token. There is NO refresh endpoint — when
the server answers 401 the token is dead and the user must re-authenticate
with a new OTP. Never log the token, phone number or plate number.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from http import HTTPStatus
from typing import Any

import aiohttp
from homeassistant.util import dt as dt_util

from .const import (
    API_BASE_URL,
    API_TIME_ZONE,
    API_TIMEOUT,
    APPID,
    ENDPOINT_HISTORY,
    ENDPOINT_LAST_LOCATION,
    ENDPOINT_LOGIN_OTP,
    ENDPOINT_LOGIN_OTP_CHECK,
    ENDPOINT_MESSAGES,
    ENDPOINT_MY_CAR,
    ENDPOINT_REFRESH_TOKEN,
    ENDPOINT_TEST_TOKEN,
    ENDPOINT_VEHICLE_INFO,
    IPOINTER_API_BASE_URL,
    IPOINTER_APPID,
    IPOINTER_EV_TILE_FIELD,
    MIN_TOKEN_LENGTH,
)

_LOGGER = logging.getLogger(__name__)


class CheryApiError(Exception):
    """Base error for Chery Connect API failures."""


class InvalidAuthError(CheryApiError):
    """The stored token was rejected (HTTP 401)."""


class InvalidOtpError(CheryApiError):
    """The OTP code was rejected or no usable token came back."""


class BlockedError(CheryApiError):
    """The server refused the login (rescode -2, the app's /opps/ page)."""


def parse_float(value: Any) -> float | None:
    """Parse a number that may arrive as a string, else None."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().replace(",", ""))
    except TypeError, ValueError:
        return None


def parse_api_time(value: Any) -> datetime | None:
    """Parse an API time string, else None; naive times are API-local."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_time_zone(API_TIME_ZONE))
    return parsed


def parse_odometer(value: Any) -> float | None:
    """Parse the Odometer field.

    The API returns it as a formatted string with commas (the app does
    ``Odometer.replace(/,/,"")`` before using it), e.g. ``"12,345"``.
    """
    return parse_float(value)


def parse_ev_tile(vehicle_info: dict[str, Any]) -> dict[str, Any] | None:
    """Return the battery tile from an iPointer VehicleInfo, else None.

    The app reads ``JSON.parse(VehicleInfo.EVTile)[0]``. A list or object
    that arrives already decoded is accepted too.
    """
    tile: Any = vehicle_info.get(IPOINTER_EV_TILE_FIELD)
    if isinstance(tile, str):
        try:
            tile = json.loads(tile)
        except ValueError:
            return None
    if isinstance(tile, list):
        tile = tile[0] if tile else None
    return tile if isinstance(tile, dict) else None


def _elapsed_ms(start: float) -> float:
    """Return milliseconds since a time.monotonic() start."""
    return (time.monotonic() - start) * 1000


def _log_status(method: str, endpoint: str, status: int, start: float) -> None:
    """Log the HTTP status and duration of one API call."""
    _LOGGER.debug(
        "API %s %s: HTTP %s in %.0f ms", method, endpoint, status, _elapsed_ms(start)
    )


def _log_failure(method: str, endpoint: str, err: Exception, start: float) -> None:
    """Log a network failure (timeout, connection error) of one API call."""
    _LOGGER.debug(
        "API %s %s failed after %.0f ms: %s",
        method,
        endpoint,
        _elapsed_ms(start),
        repr(err),
    )


class CheryConnectApiClient:
    """Async client for the Pointer/Carasso Chery Connect API.

    The same client talks to the iPointer app's API (``ipointer=True``): it
    shares the backend, the login and the request format.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | None = None,
        *,
        ipointer: bool = False,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._token = token
        self._base_url = IPOINTER_API_BASE_URL if ipointer else API_BASE_URL
        self._appid = IPOINTER_APPID if ipointer else APPID
        self.refresh_token: str | None = None

    @property
    def token(self) -> str | None:
        """Return the current Bearer token."""
        return self._token

    def set_token(self, token: str) -> None:
        """Replace the Bearer token (after login / reauth)."""
        self._token = token

    def _headers(self, *, auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    @staticmethod
    def _check_status(resp: aiohttp.ClientResponse, endpoint: str) -> None:
        """Raise for a non-200 status; 401 means the token is dead."""
        if resp.status == HTTPStatus.UNAUTHORIZED:
            raise InvalidAuthError("Token rejected by the server")
        if resp.status != HTTPStatus.OK:
            raise CheryApiError(f"Request to {endpoint} failed with HTTP {resp.status}")

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        """Send a request to {API}{endpoint} and return the parsed JSON object.

        Every call is logged at debug level: method, endpoint, the request
        field names (never values: they hold the phone, plate and code),
        status, duration and the response field names.
        """
        url = f"{self._base_url}{endpoint}"
        _LOGGER.debug(
            "API call %s %s, request fields: %s",
            method,
            endpoint,
            sorted(data) if data else "none",
        )
        start = time.monotonic()
        try:
            async with self._session.request(
                method,
                url,
                json=data if method == "POST" else None,
                headers=self._headers(auth=auth),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                _log_status(method, endpoint, resp.status, start)
                self._check_status(resp, endpoint)
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            _log_failure(method, endpoint, err, start)
            raise CheryApiError(f"Request to {endpoint} failed: {err}") from err
        except ValueError as err:
            # An HTML maintenance or WAF page instead of JSON.
            _LOGGER.debug("API %s %s: response is not JSON", method, endpoint)
            raise CheryApiError(f"Invalid JSON from {endpoint}") from err
        if not isinstance(payload, dict):
            _LOGGER.debug(
                "API %s %s: expected a JSON object, got %s",
                method,
                endpoint,
                type(payload).__name__,
            )
            raise CheryApiError(f"Unexpected response from {endpoint}")
        _LOGGER.debug(
            "API %s %s: %d fields: %s", method, endpoint, len(payload), sorted(payload)
        )
        return payload

    async def _post(
        self, endpoint: str, data: dict[str, Any] | None = None, *, auth: bool = True
    ) -> dict[str, Any]:
        """POST a JSON body."""
        return await self._request("POST", endpoint, data or {}, auth=auth)

    async def request_otp(self, mobile_phone: str, v_number: str) -> dict[str, Any]:
        """Ask the server to send an SMS OTP.

        Returns the raw response (``res`` message and ``rescode``).
        ``rescode`` 1 means the SMS was sent; -2 means the login was
        refused. No Authorization header is sent here.
        """
        payload = await self._post(
            ENDPOINT_LOGIN_OTP,
            {"MobilePhone": mobile_phone, "VNumber": v_number, "appid": self._appid},
            auth=False,
        )
        _LOGGER.debug("SMS code request answered rescode=%s", payload.get("rescode"))
        if payload.get("rescode") == -2:
            raise BlockedError("Login refused by the server")
        return payload

    async def check_otp(self, mobile_phone: str, v_number: str, code: str) -> str:
        """Exchange the SMS code for a Bearer token and return it.

        The app treats the login as successful only when the returned
        token is longer than 10 characters.
        """
        payload = await self._post(
            ENDPOINT_LOGIN_OTP_CHECK,
            {"MobilePhone": mobile_phone, "VNumber": v_number, "Code": code},
            auth=False,
        )
        token = payload.get("token")
        if not isinstance(token, str) or len(token) <= MIN_TOKEN_LENGTH:
            _LOGGER.debug("SMS code check returned no usable token")
            raise InvalidOtpError("No usable token returned for the OTP code")
        self._token = token
        refresh = payload.get("refresh_token")
        self.refresh_token = refresh if isinstance(refresh, str) and refresh else None
        return token

    async def refresh(self, refresh_token: str) -> str:
        """Get a new token with the refresh token (iPointer only).

        The refresh token is sent as the Bearer, as the app does.
        """
        old_token, self._token = self._token, refresh_token
        try:
            payload = await self._post(ENDPOINT_REFRESH_TOKEN, {})
        finally:
            self._token = old_token
        token = payload.get("token")
        if not isinstance(token, str) or len(token) <= MIN_TOKEN_LENGTH:
            _LOGGER.debug("Token refresh returned no usable token")
            raise InvalidAuthError("No usable token returned by the refresh")
        self._token = token
        return token

    async def test_token(self) -> bool:
        """Validate the stored token with TestToken (GET).

        Only the status matters: 200 means the token is valid and 401
        means it is dead. The body is not a JSON object (it can be a bare
        value or plain text), so it is never parsed.
        """
        url = f"{self._base_url}{ENDPOINT_TEST_TOKEN}"
        _LOGGER.debug("API call GET %s (token check)", ENDPOINT_TEST_TOKEN)
        start = time.monotonic()
        try:
            async with self._session.get(
                url,
                headers=self._headers(auth=True),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                _log_status("GET", ENDPOINT_TEST_TOKEN, resp.status, start)
                self._check_status(resp, ENDPOINT_TEST_TOKEN)
        except (aiohttp.ClientError, TimeoutError) as err:
            _log_failure("GET", ENDPOINT_TEST_TOKEN, err, start)
            raise CheryApiError(
                f"Request to {ENDPOINT_TEST_TOKEN} failed: {err}"
            ) from err
        return True

    async def get_vehicle_info(self) -> dict[str, Any]:
        """Fetch VehicleInfo (POST, empty body)."""
        return await self._post(ENDPOINT_VEHICLE_INFO, {})

    async def get_last_location(self) -> dict[str, Any]:
        """Fetch lastLocation (POST, empty body)."""
        return await self._post(ENDPOINT_LAST_LOCATION, {})

    async def get_my_car(self, tab_id: int) -> dict[str, Any]:
        """Fetch one myCar tab (POST {"tabId": n}), as the app's personal zone."""
        return await self._post(ENDPOINT_MY_CAR, {"tabId": tab_id})

    async def get_history(self) -> dict[str, Any]:
        """Fetch the recorded trip trace (POST, empty body)."""
        return await self._post(ENDPOINT_HISTORY, {})

    async def get_messages(self) -> dict[str, Any]:
        """Fetch the importer's messages (POST, empty body)."""
        return await self._post(ENDPOINT_MESSAGES, {})
