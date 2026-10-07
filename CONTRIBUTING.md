# Contributing

Open a focused issue or pull request with the source commit, a reproducible case, expected behavior and actual result. Separate driver changes, build changes and documentation. Preserve upstream license headers.

Run `python3 tools/run_portable_tests.py` before proposing a change. The snapshot check intentionally pins the initial candidate; if you change a pinned file, document why and update its matching size/hash entry in `docs/source-snapshot.json` as part of the reviewed patch. Do not update hashes merely to hide an unexplained mismatch.

Changes touching USB parsing, NTB bounds, queues or lifecycle behavior need regression fixtures. Changes that depend on WDF scheduling, power transitions or hardware must also provide real-device results; portable shims are not substitutes. Report build warnings and failed tests, not just successes.

Use neutral build paths and never commit SYS/PDB/CAT outputs, PFX/private keys, tokens, credentials, OEM exports, full device dumps or raw ETL captures. Redact serials, interface GUIDs, usernames and management addresses. Use synthetic fixtures where possible. New file-transfer targets on Windows should use a dedicated directory on C, not D, with test-owned cleanup only.

For a binary release, freeze a reviewed commit, build in a controlled toolchain, record checksums/provenance, verify signatures/catalog membership and complete a hardware matrix. Mark experimental test-signed artifacts distinctly from Microsoft-signed packages. Do not add unattended installers that alter boot-security or machine-wide policies.
