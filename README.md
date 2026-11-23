# hass-chery-connect-il

Home Assistant custom integration for **Chery Connect** (Carasso / Pointer)
— vehicle telemetry via owner OTP login. Read-only, v1.

## What it does

Polls the same API the Chery Connect app (v1.5.5) uses and exposes:

- **Sensors:** odometer, fuel level, range, 12V battery voltage, speed,
  electric range, tyre pressure (4 wheels), next service / insurance /
  licence dates
- **Binary sensors:** charging, engine on
- **Device tracker:** vehicle location, address, GPS time, speed, direction

## Login

Add the integration in Home Assistant, enter the mobile phone number and
vehicle number you use in the Chery Connect app, then enter the SMS code.
The token is stored in the config entry.

There is **no refresh token** in the app's API: when the server rejects the
token (HTTP 401), Home Assistant asks you to re-authenticate with a new
SMS code.

## Polling

Default refresh: **10 minutes**, minimum **5 minutes** (configurable in
the integration options). Each cycle makes two API calls
(`VehicleInfo` + `lastLocation`).

## Install (HACS, custom repository)

This repository is **private**. Installing a private repository in HACS
needs a GitHub token — see the HACS documentation for custom repositories.
(This step is unverified; it has not been tested yet.)

## Notes

- Read-only: the API exposes no remote commands (lock/unlock/start), so
  none are implemented.
- One vehicle per config entry in v1 (the app itself supports up to 8).
- `IMPLEMENTATION_NOTES.md` lists what was deliberately left out and what
  still needs a live login test.

## Development

Requires Python 3.14 (same as Home Assistant 2026.10).

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest                       # Home Assistant test harness
ruff check . && ruff format --check .   # Home Assistant core lint rules
```

Validate the manifest and translations with hassfest:

```bash
docker run --rm -v "$PWD":/github/workspace ghcr.io/home-assistant/hassfest
```
