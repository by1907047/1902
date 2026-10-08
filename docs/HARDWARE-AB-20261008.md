# USB3 mode comparison, 2026-10-08

Source-only evidence update. The installed driver was commit
`d7fd6d67a680f923de56eef638eb3f58aade5ad3`, locally test-signed; it was
not rebuilt or changed during this series. No binary is published here.

## Result

The prespecified balanced order was `1, 3, 3, 1, 1, 3`: three runs per
mode on the same USB3 connection, cable, port and MTU 8000, with the same
64 MiB SHA256-checked bidirectional payload harness. Each original run had
a 600 s limit. Mode 1 instruments OUT; mode 3 also enables recovery.

| Round | Mode | Total original checked pairs | Original terminal duration (s) | Initiating OUT XACT_ERROR |
| --- | --- | --- | --- | --- |
| 1 | 1 | 9 | 14.132 | Yes |
| 2 | 3 | 2 | 9.627 | Yes |
| 3 | 3 | 107 | 72.917 | Yes |
| 4 | 1 | 1019 | 600.777 | No |
| 5 | 1 | 0 | 8.428 | Yes |
| 6 | 3 | 535 | 601.216 | No |

Each mode had two failed runs and one clean ten-minute run. This did not
reproduce a stability advantage of mode 3; the small sample does not establish
equal failure rates or an initiating cause. Total workstation CPU samples
varied from 6% to 65%; other computations were left unchanged, not controlled.
The differing pair counts are not an isolated throughput comparison either.

**Measurement limits:** DebugView CLI file output was buffered until teardown
on short runs. Watcher discovery time is not fault time. Live stop-on-first-error
and the intended conditional fresh probe were not achieved. Durations include
terminal timeouts, and counts can include mode-3 traffic after recovery; neither
is time/pairs-before-first-error. Original failed runs remain failed.

## Recovery really progressed, then failed again

In round 2, pipe reset/start succeeded after the first XACT_ERROR. The driver
logged a new offered send and a new success. Exact-device/OUT-pipe UCX ETW
independently counted **7314 successful OUT completions between the first and
second errors**, matching the driver counter change. The second error arrived
about 1.011 s after restart, was skipped during the ten-second cooldown, and
subsequent sends timed out. Only one of three attempts had been consumed.

Round 3's driver logs recorded two successful restarts with new OUT successes.
Errors recurred about 18.660 s and 0.073 s after the respective restarts. The
last was skipped during cooldown and timeouts followed. Its large circular ETW
was retained but not decoded for this update.

This establishes transient new OUT progress, **not durable end-to-end recovery**.
The existing policy never re-arms a cooldown-skipped error. No change to that
policy, attempt budget or driver code is included here.

A separate bounded 120 s follow-up completed 106 checksum-verified pairs with
no initiating error. Its fresh recovery probe was not triggered; that acceptance
remains inconclusive. The extra run is not included in the six-run comparison.

## First-error evidence and remaining work

Round 2's first OUT request had rendered requested/completed lengths of
32136/20480 bytes, 4.245 ms after offer; round 5 had 32136/24576 bytes,
4.234 ms after offer. The same requested length had already succeeded 1856
and 383 times respectively. OUT depths were 40 and 43, against earlier peaks
of 45 and 50. These are UCX fields, not captured USB packets, and do not identify
the initiating cause. Both decoded captures reported zero lost events.

Next proposed work is a design review of bounded deferred recovery after a
cooldown skip, and a separate fixed-mode comparison changing only the physical
path. Neither was implemented here. No security/power policy was changed, no
unrelated computation was stopped, and no failed payload was silently retried.
The experiment was restored to off. PR #1 remains unmerged; this PR stays draft.
