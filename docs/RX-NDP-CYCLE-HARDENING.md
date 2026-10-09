# Cyclic RX NDP header hardening

Commit `38709d3` adds allocation-free, whole-header-chain preflight before the
first RX datagram can be exposed. Previously a crafted cyclic NTB16/NTB32
NDP chain could repeatedly deliver the same frames before the existing
table-visit budget rejected it. This is a demonstrated parser defect in
synthetic production-template fixtures, not an observed malformed live
packet or the identified cause of an OUT transaction error.

Floyd traversal validates header bounds and rejects cycles without requiring
ascending/nonoverlapping table addresses. Subtraction-form bounds avoid
integer wrap. Failed initialization clears the next-table index; normal
buffer reinitialization clears parsing state. The existing delivery visit
budget remains. Earlier fully accepted finite chains remain accepted,
including nonmonotonic/shared-DPE fixtures.

This is header/cycle hardening, not all-or-nothing DPE validation: a later bad
DPE still rejects that table and subsequent tables after earlier valid
frames may have been delivered. Arbitrarily overlapping tables can still
cause high bounded DPE work; do not describe total parsing as globally
linear. TX formatting, pipe recovery, timeout and power policies are
unchanged by this patch.

Production-template portable regression/sanitizer tests and native
Debug/Release builds/INF validation passed; local test-signed installation
and an identity-specific mode-2 600 s original passed (1174 UD pairs,
2348 full SHA checks). Native evidence supports one old-request-drain,
endpoint-reset and new-OUT-success chain with later full-SHA progress;
global analysis quality still fails startup IN pairing. A separate
default-mode0 C-file smoke passed. These are finite observations, not
trigger elimination, long-term stability or RX-caused-OUT evidence.
Earlier `59d64b7` passes and cloud-reported scratch fuzzing are not
substitutes for this revision's qualification. There is no public driver
binary or Microsoft signature, and the PR remains draft/unmerged.
