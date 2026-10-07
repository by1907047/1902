# Contributing

Open a focused issue or pull request with the source commit, a reproducible case, expected behavior and actual result. Separate driver changes, build changes and documentation. Preserve upstream license headers.

Run `python3 tools/run_portable_tests.py` before proposing a change. `docs/source-snapshot.json` is the immutable baseline for tag `v0.1.0-alpha.1`; never edit it. If you change, add or remove a file under `NCM-Driver-for-Windows/` or `tests/`, document why and run `python3 tools/update_source_current.py` to record it in `docs/source-current.json` as part of the reviewed patch. Do not regenerate that list merely to hide an unexplained mismatch.

Changes touching USB parsing, NTB bounds, queues or lifecycle behavior need regression fixtures. Changes that depend on WDF scheduling, power transitions or hardware must also provide real-device results; portable shims are not substitutes. Report build warnings and failed tests, not just successes.

Use neutral build paths and never commit SYS/PDB/CAT outputs, PFX/private keys, tokens, credentials, OEM exports, full device dumps or raw ETL captures. Redact serials, interface GUIDs, usernames and management addresses. Use synthetic fixtures where possible. New file-transfer targets on Windows should use a dedicated directory on C, not D, with test-owned cleanup only.

For a binary release, freeze a reviewed commit, build in a controlled toolchain, record checksums/provenance, verify signatures/catalog membership and complete a hardware matrix. Mark experimental test-signed artifacts distinctly from Microsoft-signed packages. Do not add unattended installers that alter boot-security or machine-wide policies.
