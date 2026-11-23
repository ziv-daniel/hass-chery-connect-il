"""Config flow for the Chery Connect integration.

Two steps, mirroring the app: step 1 sends the phone number + vehicle
number and the server sends an SMS OTP; step 2 exchanges the code for a
Bearer token. There is no refresh token, so an expired token triggers the
reauth flow, which repeats the same two steps and updates the entry.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    BlockedError,
    CheryApiError,
    CheryConnectApiClient,
    InvalidOtpError,
)
from .const import (
    CONF_MOBILE_PHONE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_BLOCKED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_OTP,
    ERROR_UNKNOWN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MOBILE_PHONE): str,
        vol.Required(CONF_V_NUMBER): str,
    }
)

STEP_OTP_SCHEMA = vol.Schema({vol.Required("code"): str})

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
        ): vol.All(
            vol.Coerce(int),
            vol.Range(
                min=int(MIN_SCAN_INTERVAL.total_seconds() // 60),
                max=int(MAX_SCAN_INTERVAL.total_seconds() // 60),
            ),
        ),
    }
)


class CheryConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Chery Connect config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._mobile_phone: str | None = None
        self._v_number: str | None = None
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def _get_client(self) -> CheryConnectApiClient:
        """Return an API client on the shared session."""
        return CheryConnectApiClient(async_get_clientsession(self.hass))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: phone + vehicle number, request the SMS OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            mobile_phone = str(user_input[CONF_MOBILE_PHONE]).strip()
            v_number = str(user_input[CONF_V_NUMBER]).strip()
            if not self._reauth_entry:
                await self.async_set_unique_id(v_number)
                self._abort_if_unique_id_configured()
            try:
                client = await self._get_client()
                await client.request_otp(mobile_phone, v_number)
            except BlockedError:
                errors["base"] = ERROR_BLOCKED
            except CheryApiError:
                errors["base"] = ERROR_CANNOT_CONNECT
            else:
                self._mobile_phone = mobile_phone
                self._v_number = v_number
                return await self.async_step_otp()
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: SMS code, exchange it for a token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input["code"]).strip()
            try:
                client = await self._get_client()
                token = await client.check_otp(
                    self._mobile_phone or "", self._v_number or "", code
                )
            except InvalidOtpError:
                errors["base"] = ERROR_INVALID_OTP
            except CheryApiError:
                errors["base"] = ERROR_CANNOT_CONNECT
            else:
                data = {
                    CONF_MOBILE_PHONE: self._mobile_phone,
                    CONF_V_NUMBER: self._v_number,
                    CONF_TOKEN: token,
                }
                if self._reauth_entry is not None:
                    return self.async_update_reload_and_abort(
                        self._reauth_entry, data=data
                    )
                return self.async_create_entry(
                    title=f"Chery {self._v_number}",
                    data=data,
                )
        if self._mobile_phone is None or self._v_number is None:
            # The OTP step was reached without step 1 (e.g. after a reload).
            return await self.async_step_user()
        return self.async_show_form(
            step_id="otp",
            data_schema=STEP_OTP_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Start reauthentication when the token is rejected."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        self._mobile_phone = str(entry_data.get(CONF_MOBILE_PHONE, ""))
        self._v_number = str(entry_data.get(CONF_V_NUMBER, ""))
        return await self.async_step_user(
            {
                CONF_MOBILE_PHONE: self._mobile_phone,
                CONF_V_NUMBER: self._v_number,
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return CheryConnectOptionsFlow()


class CheryConnectOptionsFlow(config_entries.OptionsFlow):
    """Handle the Chery Connect options (poll interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options: scan interval in minutes (min 5)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL,
                            int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60),
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=int(MIN_SCAN_INTERVAL.total_seconds() // 60),
                            max=int(MAX_SCAN_INTERVAL.total_seconds() // 60),
                        ),
                    ),
                }
            ),
        )
