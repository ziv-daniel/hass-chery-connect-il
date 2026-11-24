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

# The entry title shows only the plate's last digits (titles end up in
# screenshots and bug reports).
VISIBLE_PLATE_DIGITS: Final = 3

# API configuration, taken from the Chery Connect v1.5.5 app.
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
# While the engine runs or the car charges, poll every minute so a drive or
# a charge is not missed between idle polls. The app itself refreshes
# VehicleInfo every 60 s on its home screen (GAUGE_INTERVAL=6e4).
ACTIVE_SCAN_INTERVAL: Final = timedelta(minutes=1)
# The extra endpoints (distance, driver alerts, trip history, messages)
# change slowly, so they are fetched at most this often.
EXTRAS_REFRESH_INTERVAL: Final = timedelta(minutes=30)

# Endpoint names (POST {API_BASE_URL}{name}).
ENDPOINT_VEHICLE_INFO: Final = "VehicleInfo"
ENDPOINT_LAST_LOCATION: Final = "lastLocation"
ENDPOINT_TEST_TOKEN: Final = "TestToken"
ENDPOINT_LOGIN_OTP: Final = "login/otp"
ENDPOINT_LOGIN_OTP_CHECK: Final = "login/otpCheck"
ENDPOINT_MY_CAR: Final = "myCar"
ENDPOINT_HISTORY: Final = "getHistory"
ENDPOINT_MESSAGES: Final = "getMessages"

# myCar tabs, as the app's personal-zone page requests them.
MY_CAR_TAB_DISTANCE: Final = 0
MY_CAR_TAB_DRIVER_ALERTS: Final = 2

# Values the app treats as "on" for EngineOn and ElectricChargeStatus.
ENGINE_ON_VALUES: Final = frozenset({"1", "True", "true"})
CHARGING_ON_VALUES: Final = frozenset({"1"})

# Recommended-pressure field and the tyres it applies to.
TYRE_AXLES: Final = (
    ("PSI_FRONT", ("Frontlefttyrepressure", "Frontrighttyrepressure")),
    ("PSI_BACK", ("Rearlefttyrepressure", "Rearrighttyrepressure")),
)

# The app's fallback when VehicleInfo carries no maxDiff (PSI).
DEFAULT_TYRE_MAX_DIFF: Final = 2.0

# Fired once per new driver-behaviour alert from myCar tab 2.
EVENT_DRIVER_ALERT: Final = "chery_connect_driver_alert"
DRIVER_ALERT_EVENT_TYPE: Final = "driver_alert"

# Keys the extra endpoints add to the coordinator data. Lower-case so they
# can never collide with the API's own PascalCase VehicleInfo fields.
EXTRA_DISTANCE_TODAY: Final = "distance_today"
EXTRA_DISTANCE_MONTH: Final = "distance_this_month"
EXTRA_DISTANCE_MONTH_AVG: Final = "distance_monthly_average"
EXTRA_MESSAGES: Final = "messages"
EXTRA_TRIP: Final = "trip_history"
EXTRA_NEW_DRIVER_ALERTS: Final = "new_driver_alerts"

# lastLocation fields copied onto VehicleInfo when newer. The app copies all
# but EngineOn (it uses that one for the map icon); it is fresher than the
# VehicleInfo value while driving, so it is taken too.
LOCATION_OVERLAY_FIELDS: Final = (
    "Latitude",
    "Longtitude",
    "Speed",
    "Direction",
    "EngineOn",
    "InputVoltage",
    "InputVoltageStatus",
    "InputVoltageStatusText",
)

# Config flow errors.
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_OTP: Final = "invalid_otp"
ERROR_BLOCKED: Final = "blocked"
ERROR_INVALID_PHONE: Final = "invalid_phone"
ERROR_INVALID_V_NUMBER: Final = "invalid_v_number"
ERROR_UNKNOWN: Final = "unknown"
