# Source provenance

The first public release exports the frozen laboratory candidate `d522ef2-dirty-469555eaf6648073`. Its internal base commit is `d522ef239f613747155dc4a30db55447e6de5e59`; the uncommitted host change and two new tests were included in the freeze. The internal commit is an identifier, not a commit promised to exist in this repository's new public history.

| Archived identity | SHA256 |
| --- | --- |
| Original 601-file source archive | `d506a9cc587f4dac4ebc2d3b5e3b670064ea6f450c375450fbe531faa7c85b2f` |
| Frozen host/device.cpp | `4cc3e19100891afc9487621669a33c0dc8819131761af64d6fa9d5f863675c23` |
| Historical test-signed Release SYS, not distributed | `d08bc9e95f5915bccb9279c4316e66bd4faec7e4c0f916b2c269204aede2edda` |

The public Windows source and tests are byte-preserved copies of selected files from that archive. `source-snapshot.json` contains their path/size/SHA256 records; `python3 tools/check_snapshot.py` verifies every selected file. Newly added project documentation and automation are identified by the public Git commit, not by the old archive hash. The omitted 601-file archive is not a checksum for a GitHub source download.

## Exclusions

The upstream Linux subtree and its root README, private project notes, credentials, certificates, raw hardware/trace logs and build products are excluded. Legacy upstream `create-and-sign.ps1`, `install-driver.ps1` and `rebuild-driver.ps1` are excluded to avoid exposing unsafe generic certificate/installation automation as this project's setup flow. The stale `.gitmodules` file is omitted because the matching DMF files are vendored.

Later public commits change some pinned files; see the CHANGELOG "Unreleased" section. Their snapshot entries were updated with those commits, so `check_snapshot.py` now verifies the current tree, not the archived candidate. To inspect the exact candidate source, check out the `v0.1.0-alpha.1` tag.

The 0.1.0-alpha.1 release merged no later observation-only or link-speed proposal. No compiled driver function is changed for publication. The original working tree, historical artifacts and private rollback materials remain outside this clean public checkout.

The archived driver contains personal build-path strings. A neutral-path rebuild will change artifact identity and needs fresh verification, signatures and hardware tests; it must not inherit the old binary's test status automatically.
