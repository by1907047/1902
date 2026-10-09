# Source provenance

The first public release exports the frozen laboratory candidate `d522ef2-dirty-469555eaf6648073`. Its internal base commit is `d522ef239f613747155dc4a30db55447e6de5e59`; the uncommitted host change and two new tests were included in the freeze. The internal commit is an identifier, not a commit promised to exist in this repository's new public history.

| Archived identity | SHA256 |
| --- | --- |
| Original 601-file source archive | `d506a9cc587f4dac4ebc2d3b5e3b670064ea6f450c375450fbe531faa7c85b2f` |
| Frozen host/device.cpp | `4cc3e19100891afc9487621669a33c0dc8819131761af64d6fa9d5f863675c23` |
| Historical test-signed Release SYS, not distributed | `d08bc9e95f5915bccb9279c4316e66bd4faec7e4c0f916b2c269204aede2edda` |

At the initial publication, the public Windows source and tests were byte-preserved copies of selected files from that archive. `source-snapshot.json` retains their immutable historical path/size/SHA256 records. Later tracked source/test changes are recorded separately in `source-current.json`; `python3 tools/check_snapshot.py` verifies both layers. Project documentation and automation are identified by the public Git commit, not by the old archive hash. The omitted 601-file archive is not a checksum for a GitHub source download.

## Exclusions

The upstream Linux subtree and its root README, private project notes, credentials, certificates, raw hardware/trace logs and build products are excluded. Legacy upstream `create-and-sign.ps1`, `install-driver.ps1` and `rebuild-driver.ps1` are excluded to avoid exposing unsafe generic certificate/installation automation as this project's setup flow. The stale `.gitmodules` file is omitted because the matching DMF files are vendored.

The initial publication did not include the later observation-only or link-speed proposals and did not change compiled driver functions merely for publication. This is a historical baseline statement, not the status of subsequent commits. For the independent NTB changes and their revision-specific qualification boundary, see [NTB-HARDENING.md](NTB-HARDENING.md). The original working tree, historical artifacts and private rollback materials remain outside this public checkout.

The archived driver contains personal build-path strings. A neutral-path rebuild will change artifact identity and needs fresh verification, signatures and hardware tests; it must not inherit the old binary's test status automatically.
