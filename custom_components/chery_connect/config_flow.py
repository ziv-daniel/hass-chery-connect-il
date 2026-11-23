"""Config flow for the Chery Connect integration.

Two steps, mirroring the app: step 1 sends the phone number + vehicle
number and the server sends an SMS OTP; step 2 exchanges the code for a
Bearer token. There is no refresh token, so an expired token triggers the
reauth flow: the user confirms, a new SMS is sent for the same vehicle,
and only the token in the entry is replaced.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

# HA 2026.10 replaced voluptuous with probatio and maps `import voluptuous`
# to it at runtime. Importing voluptuous keeps the flow working on the older
# HA versions hacs.json still allows; type-check against what HA really uses.
if TYPE_CHECKING:
    import probatio as vol
else:
    import voluptuous as vol

from .api import BlockedError, CheryApiError, CheryConnectApiClient, InvalidOtpError
from .const import (
    CONF_CODE,
    CONF_MOBILE_PHONE,
    CONF_RESEND,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_BLOCKED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_INPUT,
    ERROR_INVALID_OTP,
    ERROR_UNKNOWN,
    IL_COUNTRY_CODE,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MOBILE_PHONE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEL)
        ),
        vol.Required(CONF_V_NUMBER): str,
    }
)

STEP_OTP_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CODE, default=""): str,
        vol.Optional(CONF_RESEND, default=False): bool,
    }
)


def normalize_v_number(value: str) -> str:
    """Return the vehicle number as digits only ("12-345-67" -> "1234567")."""
    return re.sub(r"\D", "", value)


def normalize_phone(value: str) -> str:
    """Return the phone as the app sends it: local 05x digits."""
    digits = re.sub(r"\D", "", value)
    if digits.startswith(IL_COUNTRY_CODE):
        return f"0{digits.removeprefix(IL_COUNTRY_CODE)}"
    return digits


def _minutes(value: timedelta) -> int:
    """Return a timedelta constant in whole minutes."""
    return int(value.total_seconds() // 60)


def options_schema(current: int) -> vol.Schema:
    """Return the options schema with the current scan interval as default."""
    interval_range = vol.Range(
        min=_minutes(MIN_SCAN_INTERVAL), max=_minutes(MAX_SCAN_INTERVAL)
    )
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                vol.Coerce(int), interval_range
            )
        }
    )


class CheryConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Chery Connect config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._mobile_phone = ""
        self._v_number = ""

    async def _send_otp(self) -> str | None:
        """Ask the server to SMS a code; return an error key on failure."""
        client = CheryConnectApiClient(async_get_clientsession(self.hass))
        try:
            await client.request_otp(self._mobile_phone, self._v_number)
        except BlockedError:
            return ERROR_BLOCKED
        except CheryApiError:
            return ERROR_CANNOT_CONNECT
        except Exception:
            _LOGGER.exception("Unexpected error requesting the SMS code")
            return ERROR_UNKNOWN
        return None

    async def _check_otp(self, code: str) -> tuple[str | None, str | None]:
        """Exchange the code for a token; return (token, error key)."""
        client = CheryConnectApiClient(async_get_clientsession(self.hass))
        try:
            token = await client.check_otp(self._mobile_phone, self._v_number, code)
        except InvalidOtpError:
            return None, ERROR_INVALID_OTP
        except CheryApiError:
            return None, ERROR_CANNOT_CONNECT
        except Exception:
            _LOGGER.exception("Unexpected error checking the SMS code")
            return None, ERROR_UNKNOWN
        return token, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: phone + vehicle number, request the SMS OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._mobile_phone = normalize_phone(user_input[CONF_MOBILE_PHONE])
            self._v_number = normalize_v_number(user_input[CONF_V_NUMBER])
            if not self._mobile_phone or not self._v_number:
                errors["base"] = ERROR_INVALID_INPUT
            else:
                await self.async_set_unique_id(self._v_number)
                self._abort_if_unique_id_configured()
                if (error := await self._send_otp()) is None:
                    return await self.async_step_otp()
                errors["base"] = error
        schema = self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: enter the SMS code, or ask for a new one."""
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get(CONF_RESEND):
            if error := await self._send_otp():
                errors["base"] = error
        elif user_input is not None:
            code = str(user_input.get(CONF_CODE, "")).strip()
            token, error = await self._check_otp(code) if code else (None, None)
            if token is not None:
                return self._async_finish(token)
            errors["base"] = error or ERROR_INVALID_OTP
        return self.async_show_form(
            step_id="otp", data_schema=STEP_OTP_SCHEMA, errors=errors
        )

    def _async_finish(self, token: str) -> ConfigFlowResult:
        """Create the entry, or replace only the token on reauth."""
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CONF_TOKEN: token}
            )
        return self.async_create_entry(
            title=f"Chery {self._v_number}",
            data={
                CONF_MOBILE_PHONE: self._mobile_phone,
                CONF_V_NUMBER: self._v_number,
                CONF_TOKEN: token,
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication when the token is rejected."""
        self._mobile_phone = str(entry_data[CONF_MOBILE_PHONE])
        self._v_number = str(entry_data[CONF_V_NUMBER])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send a new SMS only after the user confirms; the vehicle is fixed."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(self._v_number)
            self._abort_if_unique_id_mismatch()
            if (error := await self._send_otp()) is None:
                return await self.async_step_otp()
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={CONF_V_NUMBER: self._v_number},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CheryConnectOptionsFlow()


class CheryConnectOptionsFlow(OptionsFlow):
    """Handle the Chery Connect options (poll interval)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options: scan interval in minutes."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, _minutes(DEFAULT_SCAN_INTERVAL)
        )
        return self.async_show_form(step_id="init", data_schema=options_schema(current))
