"""Config flow for the Chery Connect integration.

Two steps, mirroring the app: step 1 sends the phone number + vehicle
number and the server sends an SMS OTP; step 2 exchanges the code for a
Bearer token. There is no refresh token, so an expired token triggers the
reauth flow: the user confirms, a new SMS is sent for the same vehicle,
and only the token in the entry is replaced.

The options flow can also connect the iPointer app's API with the same
two SMS steps. It is the only source of real battery data for cars such as
the Tiggo 8 PHEV.
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
from homeassistant.core import HomeAssistant, callback
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
    CONF_IPOINTER_REFRESH_TOKEN,
    CONF_IPOINTER_TOKEN,
    CONF_MOBILE_PHONE,
    CONF_RESEND,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_V_NUMBER,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_BLOCKED,
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_OTP,
    ERROR_INVALID_PHONE,
    ERROR_INVALID_V_NUMBER,
    ERROR_UNKNOWN,
    IL_COUNTRY_CODE,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    VISIBLE_PLATE_DIGITS,
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


# What the user may type: digits and dashes only (the phone may also start
# with "+" for +972). Letters, spaces and other symbols are rejected rather
# than silently stripped, so a typo never reaches the server.
_V_NUMBER_RE = re.compile(r"[0-9-]*[0-9][0-9-]*")
_PHONE_RE = re.compile(r"\+?[0-9-]*[0-9][0-9-]*")


def is_valid_v_number(value: str) -> bool:
    """Return True if the plate has only digits and dashes."""
    return _V_NUMBER_RE.fullmatch(value.strip()) is not None


def is_valid_phone(value: str) -> bool:
    """Return True if the phone has only digits and dashes (optional leading +)."""
    return _PHONE_RE.fullmatch(value.strip()) is not None


def normalize_v_number(value: str) -> str:
    """Return the vehicle number as digits only ("12-345-67" -> "1234567")."""
    return re.sub(r"\D", "", value)


def normalize_phone(value: str) -> str:
    """Return the phone as the app sends it: local 05x digits."""
    digits = re.sub(r"\D", "", value)
    if digits.startswith(IL_COUNTRY_CODE):
        return f"0{digits.removeprefix(IL_COUNTRY_CODE)}"
    return digits


def mask_v_number(v_number: str) -> str:
    """Return the plate with all but its last digits hidden ("1234567" -> "••••567")."""
    hidden = max(len(v_number) - VISIBLE_PLATE_DIGITS, 0)
    return "•" * hidden + v_number[hidden:]


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


async def async_send_otp(
    hass: HomeAssistant, phone: str, v_number: str, *, ipointer: bool = False
) -> str | None:
    """Ask the server to SMS a code; return an error key on failure."""
    client = CheryConnectApiClient(async_get_clientsession(hass), ipointer=ipointer)
    try:
        await client.request_otp(phone, v_number)
    except BlockedError:
        return ERROR_BLOCKED
    except CheryApiError:
        return ERROR_CANNOT_CONNECT
    except Exception:
        _LOGGER.exception("Unexpected error requesting the SMS code")
        return ERROR_UNKNOWN
    return None


async def async_check_otp(
    hass: HomeAssistant,
    phone: str,
    v_number: str,
    code: str,
    *,
    ipointer: bool = False,
) -> tuple[CheryConnectApiClient | None, str | None]:
    """Exchange the code for a token; return (logged-in client, error key)."""
    client = CheryConnectApiClient(async_get_clientsession(hass), ipointer=ipointer)
    try:
        await client.check_otp(phone, v_number, code)
    except InvalidOtpError:
        return None, ERROR_INVALID_OTP
    except CheryApiError:
        return None, ERROR_CANNOT_CONNECT
    except Exception:
        _LOGGER.exception("Unexpected error checking the SMS code")
        return None, ERROR_UNKNOWN
    return client, None


class CheryConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Chery Connect config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._mobile_phone = ""
        self._v_number = ""

    async def _send_otp(self) -> str | None:
        """Ask the server to SMS a code; return an error key on failure."""
        return await async_send_otp(self.hass, self._mobile_phone, self._v_number)

    async def _check_otp(self, code: str) -> tuple[str | None, str | None]:
        """Exchange the code for a token; return (token, error key)."""
        client, error = await async_check_otp(
            self.hass, self._mobile_phone, self._v_number, code
        )
        return (client.token if client is not None else None), error

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: phone + vehicle number, request the SMS OTP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            phone = str(user_input[CONF_MOBILE_PHONE])
            v_number = str(user_input[CONF_V_NUMBER])
            if not is_valid_phone(phone):
                errors[CONF_MOBILE_PHONE] = ERROR_INVALID_PHONE
            if not is_valid_v_number(v_number):
                errors[CONF_V_NUMBER] = ERROR_INVALID_V_NUMBER
            if not errors:
                self._mobile_phone = normalize_phone(phone)
                self._v_number = normalize_v_number(v_number)
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
            title=f"Chery {mask_v_number(self._v_number)}",
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
    """Handle the options: poll interval and the iPointer battery source."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        menu = ["settings", "ipointer"]
        if CONF_IPOINTER_TOKEN in self.config_entry.data:
            menu.append("ipointer_disconnect")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the scan interval in minutes."""
        if user_input is not None:
            return self.async_create_entry(
                data={**self.config_entry.options, **user_input}
            )
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, _minutes(DEFAULT_SCAN_INTERVAL)
        )
        return self.async_show_form(
            step_id="settings", data_schema=options_schema(current)
        )

    async def _send_ipointer_otp(self) -> str | None:
        """Ask iPointer to SMS a code to the entry's phone, for its vehicle."""
        return await async_send_otp(
            self.hass,
            self.config_entry.data[CONF_MOBILE_PHONE],
            self.config_entry.data[CONF_V_NUMBER],
            ipointer=True,
        )

    async def async_step_ipointer(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Send the iPointer SMS only after the user confirms."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await self._send_ipointer_otp()) is None:
                return await self.async_step_ipointer_otp()
            errors["base"] = error
        return self.async_show_form(step_id="ipointer", errors=errors)

    async def async_step_ipointer_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the iPointer SMS code, or ask for a new one."""
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get(CONF_RESEND):
            if error := await self._send_ipointer_otp():
                errors["base"] = error
        elif user_input is not None:
            code = str(user_input.get(CONF_CODE, "")).strip()
            client, error = (
                await async_check_otp(
                    self.hass,
                    self.config_entry.data[CONF_MOBILE_PHONE],
                    self.config_entry.data[CONF_V_NUMBER],
                    code,
                    ipointer=True,
                )
                if code
                else (None, None)
            )
            if client is not None and client.token is not None:
                data = {**self.config_entry.data, CONF_IPOINTER_TOKEN: client.token}
                data.pop(CONF_IPOINTER_REFRESH_TOKEN, None)
                if client.refresh_token:
                    data[CONF_IPOINTER_REFRESH_TOKEN] = client.refresh_token
                return self._async_save_data(data)
            errors["base"] = error or ERROR_INVALID_OTP
        return self.async_show_form(
            step_id="ipointer_otp", data_schema=STEP_OTP_SCHEMA, errors=errors
        )

    async def async_step_ipointer_disconnect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Stop using iPointer after the user confirms."""
        if user_input is not None:
            data = {
                key: value
                for key, value in self.config_entry.data.items()
                if key not in (CONF_IPOINTER_TOKEN, CONF_IPOINTER_REFRESH_TOKEN)
            }
            return self._async_save_data(data)
        return self.async_show_form(step_id="ipointer_disconnect")

    def _async_save_data(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Store new entry data; the update listener reloads the entry."""
        self.hass.config_entries.async_update_entry(self.config_entry, data=data)
        return self.async_create_entry(data=dict(self.config_entry.options))
