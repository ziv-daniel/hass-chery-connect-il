# Changelog

## 0.3.0b1 (2026-11-24, beta)

### Added
- Faster refresh while driving or charging: every minute while the engine
  runs or the car charges, back to your interval when parked. Engine on now
  also comes from the fresher location data.
- EV battery level and charge status sensors (plug-in cars).
- Tyre pressure low binary sensor, using the recommended pressure and the
  allowed difference the car reports.
- Distance today, distance this month and monthly distance average sensors.
- Last trip sensor (from the app's trip history) and a messages sensor.
- Speeding, harsh acceleration and harsh braking counts this month (the
  app's driver-behaviour graph) and a next service type sensor.
- Driver alert event entity and a `chery_connect_driver_alert` event for each
  new driver-behaviour alert.

### Changed
- Tyre pressure is shown in PSI, the unit the car reports and the one used at
  Israeli gas stations, with no decimals. Metric installs used to convert it to
  kPa (e.g. 262.000766 kPa for 38 PSI). Existing sensors switch automatically
  unless you picked a unit yourself in the entity settings.

### Notes
- Distance, trip, messages and driver alerts are fetched every 30 minutes.
  Their payloads are taken from the app's code, not from a live capture. If
  one of them fails, only its entity is affected.

## 0.2.3 (2026-11-24)

### Changed
- Renamed the integration display name to "Chery Car Connect IL" (HACS,
  the Add integration list and the options dialog). The domain stays
  `chery_connect`, so existing setups keep working with no changes.

## 0.2.2 (2026-11-24)

### Fixed
- Setup no longer fails with "Unexpected response from TestToken": the token
  check now looks only at the HTTP status, not the response body.

### Added
- Logging: setup logs the refresh interval and every scheduled refresh logs
  one summary line (info, always visible). Debug logging also records
  every API call (endpoint, status, duration, response field names), each
  scheduled refresh, and why a call failed. The token, phone, plate, SMS code
  and coordinates are never logged.

### Changed
- The phone and vehicle number fields accept only digits and dashes (the
  phone may start with +). Letters, spaces or other symbols show an error on
  that field instead of being silently removed.

## 0.2.1 (2026-11-24)

### Changed
- Brand icon is now a generic connected car instead of the Chery emblem.

## 0.2.0 (2026-11-24)

### Fixed
- An expired token now opens re-authentication instead of failing setup.
- Unique ids and the device no longer break when the first update fails.
- Service, insurance and licence dates no longer crash; they are date sensors.
- HTML or invalid JSON responses are reported as connection errors.
- Re-authentication asks before sending an SMS and cannot switch vehicle.

### Added
- "Send a new code" on the SMS step; phone and plate normalisation.
- Translated entity names (English, Hebrew) and icons.
- Diagnostics download with token, phone, plate and location redacted.
- Test suite, CI workflow, security policy.
- README with install and setup buttons; repository is public.
- Brand icons (light and dark) for the integrations page and HACS.

### Changed
- Only entities for fields the vehicle reports are created.
- Voltage, tyre and date sensors are diagnostic; speed is disabled by default.
- Sensors no longer carry the address and GPS time (the tracker does).
- New entries are titled with a masked plate.

## 0.1.0
- First version: sensors, binary sensors and device tracker over OTP login.
