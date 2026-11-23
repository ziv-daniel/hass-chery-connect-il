# Development notes

The integration talks to the same private API as the Chery Connect app
(v1.5.5). Endpoints, field names and the login rules were taken from the
app's JavaScript; nothing here is an official contract.

## Scope decisions

- **No remote commands.** The API has none (no lock, unlock or start).
- **No `requirements` in the manifest.** Only the standard library and HA
  core are used (`aiohttp` comes with HA).
- **No warning-lamp or myCar diagnostic entities.** Warning lamps are a
  list and myCar uses a separate API; both are future work.
- **One vehicle per config entry.** The app stores up to 8 vehicles;
  multi-vehicle support (subentries) is future work.
- **Polling only.** The app's push registration adds nothing for HA.
- **`import voluptuous`, typed as probatio.** HA 2026.10 maps voluptuous to
  probatio at runtime; the import keeps older HA versions working. Switch to
  `import probatio` when the minimum HA version reaches 2026.10.

## Still needs a live payload (do not claim these work yet)

1. **Token lifetime.** The app has no refresh endpoint; a real login will
   show how long a token survives.
2. **Range sensor.** Parsing the first word of `FualLevelDesc` is verified
   in the app only for its Nissan theme, not for Chery.
3. **Timezones.** Naive `GPSDatetime` values are read as Asia/Jerusalem;
   dates are read as calendar dates.
4. **Units and types.** Tyre pressure is assumed PSI and fuel level
   percent; numbers are parsed leniently from strings.
5. **HACS install from a private repository.** Needs a GitHub token in
   HACS; untested.

## Checks

See the README's Development section. CI (`.github/workflows/ci.yml`)
runs ruff, mypy, pytest with coverage, hassfest and the HACS action.
