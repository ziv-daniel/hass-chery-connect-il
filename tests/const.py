"""Synthetic identifiers shared by the tests (no real phone, plate or token)."""

TOKEN = "t" * 32
PHONE = "0501234567"
V_NUMBER = "1234567"
CODE = "123456"
NEW_TOKEN = "n" * 32
OTHER_V_NUMBER = "7654321"

# Keys of the extras_payloads fixture for the two myCar tabs.
EXTRA_DISTANCE = "myCar distance"
EXTRA_DRIVER_ALERTS = "myCar driver alerts"
EXTRA_DRIVING_EVENTS = "myCar driving events"

# What a Tiggo 8 PHEV sends (ElectricDesign 0): fixed placeholder values.
PLACEHOLDER_ELECTRIC_FIELDS = {
    "ElectricDesign": 0,
    "ElectricChargeStatus": 0,
    "ElectricBatteryStatus": 88,
    "ElectricBatteryKM": 160,
    "ElectricBatteryChargeStatusText": None,
}
CHARGING = "binary_sensor.chery_tiggo_8_pro_charging"
ELECTRIC_ENTITY_IDS = (
    CHARGING,
    "sensor.chery_tiggo_8_pro_ev_battery",
    "sensor.chery_tiggo_8_pro_electric_range",
    "sensor.chery_tiggo_8_pro_charge_status",
)
# (platform, unique_id suffix) of the battery and charging entities.
ELECTRIC_REGISTRY_KEYS = (
    ("binary_sensor", "charging"),
    ("sensor", "ev_battery_level"),
    ("sensor", "electric_range"),
    ("sensor", "charge_status"),
)
