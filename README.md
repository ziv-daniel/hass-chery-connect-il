# Chery Car Connect IL for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![GitHub release](https://img.shields.io/github/v/release/ziv-daniel/hass-chery-connect-il)](https://github.com/ziv-daniel/hass-chery-connect-il/releases)
[![CI](https://github.com/ziv-daniel/hass-chery-connect-il/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ziv-daniel/hass-chery-connect-il/actions/workflows/ci.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-41BDF5.svg)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/github/license/ziv-daniel/hass-chery-connect-il)](LICENSE)

Read-only Home Assistant integration for cars registered in the Israeli
**Chery Connect** app (Carasso / Pointer). You log in with your phone number
and an SMS code, the same way as in the app.

> Unofficial. Not affiliated with Chery, Carasso or Pointer. It uses the
> app's private API, which can change without notice.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ziv-daniel&repository=hass-chery-connect-il&category=integration)

Or in HACS → ⋮ → **Custom repositories**, add
`https://github.com/ziv-daniel/hass-chery-connect-il` as an **Integration**.
Download **Chery Car Connect IL**, then restart Home Assistant.

### Manual

Copy `custom_components/chery_connect` into your Home Assistant
`config/custom_components/` folder and restart.

## Setup

[![Open your Home Assistant instance and start setting up Chery Car Connect IL.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=chery_connect)

1. **Settings → Devices & services → Add integration → Chery Car Connect IL**.
2. Enter the mobile number and vehicle (plate) number registered in the
   app.
3. Enter the SMS code.

Each vehicle is a separate entry. To change the refresh interval (default
10 minutes, 5–60), open the integration's **Configure** options. While the
car moves, its engine runs or it charges, the integration refreshes every
minute instead, so drives (electric ones too) and charging show up. Distance, trip, messages and driver
alerts change slowly and are fetched every 30 minutes.

## Entities

| Platform | Entities |
| --- | --- |
| Sensor | Odometer, fuel level, range, electric range, EV battery, charge status, distance today, distance this month, monthly distance average, last trip, messages, speed¹, 12V battery voltage², tyre pressure ×4², next service², insurance date², licence date² |
| Binary sensor | Charging, engine on, tyre pressure low |
| Device tracker | Location (with address, speed, direction and GPS time attributes) |
| Event | Driver alert (driver-behaviour alerts from the app) |

¹ Disabled by default. ² Diagnostic entity.

Entities are created only for the fields your car reports, so a petrol car
has no charging or electric range entity. Electric range, EV battery, charge
status and charging exist only for cars the server treats as electric (the
ones the app shows a battery screen for). For other cars, including the
Tiggo 8 PHEV, the server sends fixed placeholder values (88 %, 160 km, never
charging), so they are left out unless you connect iPointer (below). The UI
is in English and Hebrew.
There are no remote commands (lock, start), because the API doesn't offer any.

- **Tyre pressure low** is on when any tyre is below the recommended
  pressure minus the allowed difference the car reports (2 PSI if it reports
  none). The recommended pressures are attributes.
- **Last trip** is the time of the latest point of the recorded trip, with
  its start time and point count as attributes.
- **Messages** is the number of messages from the importer, with the newest
  one's title, text and time as attributes.
- **Driver alert** records each new driver-behaviour alert. Each one also
  fires a `chery_connect_driver_alert` event (`config_entry_id`, `message`,
  `time`) for automations. Alerts already in the report at startup don't
  fire.

## Real battery data from iPointer (optional)

If your car also has a Pointer iPointer service, the iPointer app shows the
real battery level, electric range and charging state, including for cars
the Chery Connect service sends placeholder values for. Both apps run on the
same Pointer backend, so the integration first tries your Chery Connect
login on iPointer. If iPointer accepts it, the battery data appears with no
extra step. If not, open the integration's **Configure** options, choose
**Connect iPointer** and
enter the SMS code iPointer sends to the phone already configured. The EV
battery, electric range, charging and charge status entities then come from
iPointer; charge status shows the time left to a full charge. Signing in
here may sign the iPointer app on your phone out.

If iPointer is unreachable, those entities show unknown rather than the
placeholder values. If its login expires, a repair issue asks you to connect
again. **Disconnect iPointer** in the same options removes the login.

## Re-authentication

The API has no refresh token. When the server rejects the stored token,
Home Assistant shows **Re-authenticate** on the integration under
**Settings → Devices & services**: open it and enter a new SMS code. If the code doesn't arrive, tick **Send a new code** and submit.

## Troubleshooting

When you report a bug, attach the diagnostics file (device page → ⋮ →
**Download diagnostics**). The token, phone, plate, coordinates and address
are redacted in that file. Don't post `.storage` files, because they contain
your token.

The log always shows one line at startup with the refresh interval and one
line per scheduled refresh. Debug logging adds a line for every API call (endpoint, HTTP status, duration,
which fields came back), for every scheduled refresh, and the shape
(field types and lengths, no values) of each distance, trip, message and
driver-alert response. These lines never
include the token, phone, plate, SMS code or coordinates. To turn it on, go
to **Settings → Devices & services → Chery Car Connect IL → ⋮ → Enable debug
logging**, or add:

```yaml
logger:
  logs:
    custom_components.chery_connect: debug
```

## Removal

Delete the integration under **Settings → Devices & services**, which
removes the stored token. Then remove it in HACS, or delete the folder.

## Development

Requires Python 3.14.

```bash
pip install -r requirements_test.txt
pytest
ruff check . && ruff format --check .
mypy custom_components
```

CI runs these checks together with hassfest and HACS validation.
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) lists the scope decisions and
the behaviour that still needs to be checked against a live car.
Security issues: see [SECURITY.md](SECURITY.md).
