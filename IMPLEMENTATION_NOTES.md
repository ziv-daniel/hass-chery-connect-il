# Implementation notes — v0.1.0 scaffold

Built 23 Nov 2026 directly from the verified API contract
(`CHERY_API_CONTRACT.md`, extracted from Chery Connect v1.5.5 app.js).
The opencode runs for this scaffold never produced output in this VM
(two `opencode run` attempts with different free models hung with zero
output and were killed by runtime restarts), so the scaffold was written
by hand from the contract instead. opencode can review it later.

## What was built

- `custom_components/chery_connect/`: `manifest.json`, `const.py`,
  `api.py`, `config_flow.py` (OTP, two steps + reauth + options),
  `coordinator.py`, `entity.py`, `sensor.py` (13 sensors),
  `binary_sensor.py` (charging, engine), `device_tracker.py`,
  `strings.json`, `translations/en.json` + `translations/he.json`.
- `hacs.json`, `README.md`, `LICENSE` (MIT, mirrored from
  hass-israel-transportation-integration), `tests/test_api.py`
  (stdlib `unittest`, mocked session — no network, no HA needed).

## Deliberately left out

- **No CI workflows** (`.github/workflows/`) — GitHub Actions billing
  freeze; add only on explicit order.
- **No `requirements`** in the manifest — only stdlib + HA core
  (`aiohttp` is provided by HA; listing it is forbidden by hassfest).
- **No remote commands** — the API has none (lock/unlock/start do not
  exist in the app).
- **No WarningLamps / myCar diagnostics entities** — WarningLamps is a
  list (`DATA.VehicleModelWarningLamps`), myCar diagnostics are a
  separate tab API; both are v2 material, not v1 sensors.
- **No multi-vehicle support** — the app stores up to 8 vehicles
  (`cp_UsersArr`); v1 is one vehicle per config entry.
- **No FCM push registration** — polling only; push adds nothing for HA.

## Still needs a live login test (do not claim these work yet)

1. **Token lifetime** — unknown. The app has no refresh endpoint; the
   first real login will show how long a token survives.
2. **Range sensor** — `FualLevelDesc` first-word parsing is verified
   only for `NissanTheme` in the app code, not for `CheryTheme`.
   If the Chery home screen shows the range differently, this sensor
   stays `unknown` and the parsing must be fixed from a live response.
3. **401 behaviour** — reauth flow triggers `ConfigEntryAuthFailed`;
   confirm HA actually shows the reauth notification.
4. **Field types** — `FualLevel`, `InputVoltage`, `Speed`, tyre
   pressures and `ElectricChargeStatus` are parsed leniently
   (strings or numbers), but a live `VehicleInfo` response should be
   checked against these assumptions.
5. **HACS install from a private repo** — needs a GitHub token in
   HACS; unverified, untested.
6. **hassfest / full pytest** — full `pytest-homeassistant-custom-
   component` cannot run locally (VM has Python 3.12, repo CI uses
   3.14). Run hassfest + the HA test suite in CI or on a machine
   with Python 3.14 before any release.
