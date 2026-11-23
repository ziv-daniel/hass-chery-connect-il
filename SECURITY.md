# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's
"Report a vulnerability" (Security → Advisories), not in a public issue.
Include steps to reproduce and the affected version. You should get an
answer within 7 days.

## What this integration stores

- The login token, mobile phone and vehicle number, in the Home Assistant
  config entry (`.storage/core.config_entries`), like every integration.
- Nothing is sent anywhere except the Chery Connect API over HTTPS.

Never share raw logs, `.storage` files or captured app traffic: they can
contain your token. Use the redacted diagnostics download instead.
