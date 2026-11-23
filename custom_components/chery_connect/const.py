"""Constants for the Chery Connect integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "chery_connect"

# Configuration keys stored in the config entry.
CONF_MOBILE_PHONE: Final = "mobile_phone"
CONF_V_NUMBER: Final = "v_number"
CONF_TOKEN: Final = "token"
CONF_SCAN_INTERVAL: Final = "scan_interval"

# Config flow form fields (not stored in the entry).
CONF_CODE: Final = "code"
CONF_RESEND: Final = "resend"

# Israeli numbers may be typed as +972 5x...; the app sends 05x...
IL_COUNTRY_CODE: Final = "972"

# API configuration — verified from Chery Connect v1.5.5 app.js.
# See CHERY_API_CONTRACT.md in the workspace (not shipped in the repo).
API_BASE_URL: Final = "https://iot.pointer4u.co.il/iservices/carassoApp/api/"
APPID: Final = 34
API_TIMEOUT: Final = 15
# The app accepts a login only when the returned token is longer than this.
MIN_TOKEN_LENGTH: Final = 10
# The service is Israeli and sends GPS times without an offset; treat them
# as local Israeli time (unverified against a live payload, see issue #2).
API_TIME_ZONE: Final = "Asia/Jerusalem"

# Polling: default 10 minutes, hard floor 5 minutes, max 60 minutes.
DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=10)
MIN_SCAN_INTERVAL: Final = timedelta(minutes=5)
MAX_SCAN_INTERVAL: Final = timedelta(minutes=60)

# Endpoint names (POST {API_BASE_URL}{name}).
ENDPOINT_VEHICLE_INFO: Final = "VehicleInfo"
ENDPOINT_LAST_LOCATION: Final = "lastLocation"
ENDPOINT_TEST_TOKEN: Final = "TestToken"
ENDPOINT_LOGIN_OTP: Final = "login/otp"
ENDPOINT_LOGIN_OTP_CHECK: Final = "login/otpCheck"

# lastLocation fields the app copies onto VehicleInfo when newer.
LOCATION_OVERLAY_FIELDS: Final = (
    "Latitude",
    "Longtitude",
    "Speed",
    "Direction",
    "InputVoltage",
    "InputVoltageStatus",
    "InputVoltageStatusText",
)

# Config flow errors.
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_OTP: Final = "invalid_otp"
ERROR_BLOCKED: Final = "blocked"
ERROR_INVALID_INPUT: Final = "invalid_input"
ERROR_UNKNOWN: Final = "unknown"
