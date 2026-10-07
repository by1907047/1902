# Source provenance

The first public release exports the frozen laboratory candidate `d522ef2-dirty-469555eaf6648073`. Its internal base commit is `d522ef239f613747155dc4a30db55447e6de5e59`; the uncommitted host change and two new tests were included in the freeze. The internal commit is an identifier, not a commit promised to exist in this repository's new public history.

| Archived identity | SHA256 |
| --- | --- |
| Original 601-file source archive | `d506a9cc587f4dac4ebc2d3b5e3b670064ea6f450c375450fbe531faa7c85b2f` |
| Frozen host/device.cpp | `4cc3e19100891afc9487621669a33c0dc8819131761af64d6fa9d5f863675c23` |
| Historical test-signed Release SYS, not distributed | `d08bc9e95f5915bccb9279c4316e66bd4faec7e4c0f916b2c269204aede2edda` |

At tag `v0.1.0-alpha.1`, the public Windows source and tests are byte-preserved copies of selected files from that archive. `docs/source-snapshot.json` contains their path/size/SHA256 records and is the immutable baseline manifest. Newly added project documentation and automation are identified by the public Git commit, not by the old archive hash. The omitted 601-file archive is not a checksum for a GitHub source download.

## Baseline and current source

`python3 tools/check_snapshot.py` makes two separate claims:

| Claim | Evidence | Meaning |
| --- | --- | --- |
| Baseline provenance | `docs/source-snapshot.json`, whose SHA256 (`bdc2c2ce874cc5e8fb5a66067f2a1e421fa916a327c36daba458f5e939159221`) is pinned in the verifier; every record is compared with the file contents at tag `v0.1.0-alpha.1` (mandatory in CI) | The tagged files are the exported archived candidate |
| Current-source integrity | `docs/source-current.json` lists every file in `NCM-Driver-for-Windows/` and `tests/` that changed, was added or was removed after the baseline; every other tracked file in that scope must still match the baseline | Describes the current tree only. That source is **unreleased, not built with the WDK and not hardware-tested**; it does not inherit the candidate's hardware results |

The current-source list is maintained with `python3 tools/update_source_current.py` and reviewed with each change. It is an integrity record, not provenance: the identity of post-baseline source is the Git commit. `tools/export_snapshot.py` only regenerates the baseline from the private archive and fails if any baseline file was modified.

## Exclusions

The upstream Linux subtree and its root README, private project notes, credentials, certificates, raw hardware/trace logs and build products are excluded. Legacy upstream `create-and-sign.ps1`, `install-driver.ps1` and `rebuild-driver.ps1` are excluded to avoid exposing unsafe generic certificate/installation automation as this project's setup flow. The stale `.gitmodules` file is omitted because the matching DMF files are vendored.

Later public commits change some baseline files; see the CHANGELOG "Unreleased" section and `docs/source-current.json`. To inspect the exact candidate source, check out the `v0.1.0-alpha.1` tag.

The 0.1.0-alpha.1 release merged no later observation-only or link-speed proposal. No compiled driver function is changed for publication. The original working tree, historical artifacts and private rollback materials remain outside this clean public checkout.

The archived driver contains personal build-path strings. A neutral-path rebuild will change artifact identity and needs fresh verification, signatures and hardware tests; it must not inherit the old binary's test status automatically.
