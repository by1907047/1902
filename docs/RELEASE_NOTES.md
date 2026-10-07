# v0.1.0-alpha.1 — source-only preview

First public export of the frozen Apple `05AC:1902` Windows USB NCM reconnect candidate, with vendored DMF, retained MIT notices, English/Chinese documentation, provenance hashes and portable CI.

**No installable SYS/CAT or signing certificate is included.** The old test-signed binary embeds a personal build path and is withheld. A neutral-path rebuild, signing and fresh hardware regression are required before a binary release.

All local portable suites passed for the published source. Those tests use OS shims and do not constitute a Windows native build, kernel safety test, HLK/WHQL certification or normal Secure Boot acceptance. Historical short hardware tests are described separately in the repository.

Known open issues: USB3 download stall/recovery, sustained reliability, true sleep/wake, incorrect advertised link rates and upload/download asymmetry. Keep an independent remote-management connection.

See README, BUILDING, INSTALLING, TESTING, KNOWN_ISSUES and SIGNING before experimenting. No driver installation or security-policy change was made for this release.
