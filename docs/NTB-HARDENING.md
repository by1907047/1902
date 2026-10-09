# Independent NTB hardening candidate

This source-only candidate is based on `main` at `2148710` and extracts the
NTB reserved-field and RX header-chain changes from the reviewed development
line (`9d3f3cb` and `38709d3`). Only `common/ntb.cpp` changes in production.
The host driver, INF, link-state policy, USB power policy, and security settings
are unchanged. No experimental OUT-pipe recovery mode is introduced.

## Qualification boundary

This new combination has not yet been built with the Windows Driver Kit,
installed, or hardware-tested. Portable tests exercise the production NTB
template with local shims; they are not a native driver qualification.
Earlier build or hardware results from other commits do not qualify this
candidate. In particular, this change neither completes PR #1's locked-screen
reconnect/sustained-transfer acceptance nor establishes long-term stability.
It does not identify or claim to fix the initial USB OUT transaction-error cause.

## Production changes

- TX clears the entire NDP header before filling its fields, ensuring NDP32
  reserved fields are zero even when a dirty backing buffer is reused. Payload,
  DPE entries, and bytes beyond the emitted block are not cleared by this step.
- RX preflights every reachable NDP header before exposing a datagram. An
  allocation-free Floyd traversal rejects cycles and malformed header chains,
  including nonzero out-of-bounds next indices. Initialization failure clears
  the next-index traversal state.
- Acyclic, nonmonotonic chains and shared datagrams remain supported within
  the existing table-visit bound. Per-datagram validation is unchanged: this is
  not an all-or-nothing validation of every DPE. A later malformed DPE can still
  be found after earlier valid datagrams were delivered. Overlapping headers or
  shared DPEs can still entail substantial bounded work; this is not a claim
  that all parser work is linear in transfer bytes.

## Portable checks and source identity

Run `python3 tools/run_portable_tests.py`. The full runner retains the existing
baseline suites and adds dirty/reused NTB16/32 reserved-field controls, maximum
chain/cycle/bad-header/reuse fixtures, and source-identity verifier tests. The
new NTB probes compile the production template with ASan and UBSan. They do not
load a Windows driver or access a USB device.

`docs/source-snapshot.json` remains the immutable historical baseline.
`docs/source-current.json` records the tracked source/test delta from that
baseline. Stage newly added source/test files before running
`python3 tools/update_source_current.py`, then stage the generated manifest.
`tools/check_snapshot.py` checks both layers. CI fetches complete history so it
can also verify the baseline tag. Regenerating a source manifest is not evidence
of a native build or a hardware pass.
