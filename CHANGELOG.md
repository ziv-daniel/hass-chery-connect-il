# Changelog

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
