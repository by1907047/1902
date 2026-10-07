# Changelog

## 0.1.0-alpha.1 — 2026-10-07

First public **source-only** snapshot of the frozen `d522ef2-dirty-469555eaf6648073` reconnect candidate. This is a packaging/documentation release, not a newly validated driver fix.

- Publish the Windows driver and exact vendored DMF snapshot with upstream MIT notices.
- Include portable INF, parser, NTB, buffer, queue, adapter lifecycle and host reprepare tests.
- Add English/Chinese README, build/safety/rollback documentation, sanitized historical results, provenance and portable CI.
- Exclude Linux code, machine-specific helpers/logs, secrets and historical binaries.

Open limitations include USB3 stalls/recovery, long-duration testing, link-rate metadata, upload asymmetry and Microsoft signing. No Windows build, driver installation, security-policy change or hardware test was performed for this publication.
