"""Chery Connect API client.

Verified against the Chery Connect v1.5.5 app.js (see the workspace copy of
CHERY_API_CONTRACT.md). Auth is owner OTP: login/otp sends an SMS, then
login/otpCheck returns a Bearer token. There is NO refresh endpoint — when
the server answers 401 the token is dead and the user must re-authenticate
with a new OTP. Never log the token, phone number or plate number.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_TIMEOUT,
    APPID,
    ENDPOINT_LAST_LOCATION,
    ENDPOINT_LOGIN_OTP,
    ENDPOINT_LOGIN_OTP_CHECK,
    ENDPOINT_TEST_TOKEN,
    ENDPOINT_VEHICLE_INFO,
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
    except (TypeError, ValueError):
        return None


def parse_odometer(value: Any) -> float | None:
    """Parse the Odometer field.

    The API returns it as a formatted string with commas (the app does
    ``Odometer.replace(/,/,"")`` before using it), e.g. ``"12,345"``.
    """
    return parse_float(value)


class CheryConnectApiClient:
    """Async client for the Pointer/Carasso Chery Connect API."""

    def __init__(
        self, session: aiohttp.ClientSession, token: str | None = None
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._token = token

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

    async def _post(
        self, endpoint: str, data: dict[str, Any] | None = None, *, auth: bool = True
    ) -> dict[str, Any]:
        """POST {API}{endpoint} with a JSON body, return the parsed JSON."""
        url = f"{API_BASE_URL}{endpoint}"
        try:
            async with self._session.post(
                url,
                json=data or {},
                headers=self._headers(auth=auth),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise InvalidAuthError("Token rejected by the server")
                if resp.status != 200:
                    raise CheryApiError(
                        f"Request to {endpoint} failed with HTTP {resp.status}"
                    )
                payload = await resp.json(content_type=None)
        except (InvalidAuthError, CheryApiError):
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CheryApiError(f"Request to {endpoint} failed: {err}") from err
        if not isinstance(payload, dict):
            raise CheryApiError(f"Unexpected response from {endpoint}")
        return payload

    async def _get(self, endpoint: str) -> dict[str, Any]:
        """GET {API}{endpoint} with the Bearer token."""
        url = f"{API_BASE_URL}{endpoint}"
        try:
            async with self._session.get(
                url,
                headers=self._headers(auth=True),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise InvalidAuthError("Token rejected by the server")
                if resp.status != 200:
                    raise CheryApiError(
                        f"Request to {endpoint} failed with HTTP {resp.status}"
                    )
                payload = await resp.json(content_type=None)
        except (InvalidAuthError, CheryApiError):
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CheryApiError(f"Request to {endpoint} failed: {err}") from err
        if not isinstance(payload, dict):
            raise CheryApiError(f"Unexpected response from {endpoint}")
        return payload

    async def request_otp(self, mobile_phone: str, v_number: str) -> dict[str, Any]:
        """Ask the server to send an SMS OTP.

        Returns the raw response (``res`` message and ``rescode``).
        ``rescode`` 1 means the SMS was sent; -2 means the login was
        refused. No Authorization header is sent here.
        """
        payload = await self._post(
            ENDPOINT_LOGIN_OTP,
            {"MobilePhone": mobile_phone, "VNumber": v_number, "appid": APPID},
            auth=False,
        )
        if payload.get("rescode") == -2:
            raise BlockedError("Login refused by the server")
        return payload

    async def check_otp(
        self, mobile_phone: str, v_number: str, code: str
    ) -> str:
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
        if not isinstance(token, str) or len(token) <= 10:
            raise InvalidOtpError("No usable token returned for the OTP code")
        self._token = token
        return token

    async def test_token(self) -> bool:
        """Validate the stored token with TestToken (GET)."""
        await self._get(ENDPOINT_TEST_TOKEN)
        return True

    async def get_vehicle_info(self) -> dict[str, Any]:
        """Fetch VehicleInfo (POST, empty body)."""
        return await self._post(ENDPOINT_VEHICLE_INFO, {})

    async def get_last_location(self) -> dict[str, Any]:
        """Fetch lastLocation (POST, empty body)."""
        return await self._post(ENDPOINT_LAST_LOCATION, {})
