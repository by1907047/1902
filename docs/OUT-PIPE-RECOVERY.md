# Experimental data-pipe diagnostics and pipe-only recovery

**Status:** experimental, default-off and source-only; no public driver binary
or Microsoft signature. Source integration does not confer hardware qualification. Native build,
installation, business traffic and recovery qualification are separate gates.
Existing native-analysis/dependency warnings remain.

**2026-10-10 integration:** see the [experience and integration note](2026-10-10-lessons-and-source-integration.zh-CN.md).
In recovery mode, a terminal pipe reset/start failure now reports link down
once; successful starts of both pipes restore the indication. No idle-traffic
watchdog, payload replay, broadened OUT error classification or PnP reset is
added. Mode0/1 does not execute this reporting. The new reporting is modeled
in portable regression but has not been exercised on hardware.

`5ed5a1a` passed offline x64 Debug/Release EWDK builds and both InfVerif
checks, with native and wrapper exits zero. The existing 70/68 warnings
match `38709d3` under full-multiset/root/unchanged-line normalization (no
added or removed warnings). The new Release SYS is unsigned and uninstalled;
its SHA256 and evidence boundary are in the integration note. Later
documentation-only commits do not represent new native binary builds.

**2026-10-09 revision status:**

- `81fb3e6`: one original 300 s checked run continued after a real OUT
  transaction error and pipe-only recovery, corroborated by native ETW and
  application SHA progress. Another run failed when a fourth fault exhausted
  the old three-attempt-per-D0 budget. Both original results are retained.
- `59d64b7`: renewable time-credit recovery passed x64 Debug/Release WDK
  builds, both INF validations and local test-signed installation. Two fixed
  mode-2 600 s originals passed: 1130/1170 UD pairs and 2260/2340 checked
  transfers (4600 total). Business PASS does not mean fault-free transport.
  T1 has five independently matched native OUT transaction errors, each
  followed by current-device ResetEndpoint/SetTRDequeue success, a new
  post-reset OUT offer and its paired success, plus subsequent checked
  bidirectional SHA progress. This supports five narrow recovery chains,
  not a strict >3-uninterrupted-epoch qualification: old-request drain
  before each reset is not yet individually timed, and ordinary empty
  queue stops are not exhaustively logged in mode2. T2 records zero
  observed payload OUT XACT and only successful observed payload bulk
  statuses. Both captures pass capture-quality checks but retain global
  analysis-quality failure for eight startup unmatched IN completions
  each; neither is labeled transport-clean. Natural Deferred credit-wait
  was not exercised; portable coverage is not native coverage.
- `38709d3`: adds [cyclic RX NDP preflight](RX-NDP-CYCLE-HARDENING.md).
  Native Debug/Release builds, INF validation and local test-signed install
  passed (Release SYS SHA-256 `20AFD6D8E3AED4AE204FE71907C36AC2E71F0A5CA81D2A8E553782039D1A54C1`).
  Its separately identified corrected-tool mode-2 600 s original passed
  1174 UD pairs / 2348 complete SHA checks, 78,785,806,336 bytes per direction.
  One native OUT XACT was followed by cancellation of all 25 traced old
  outstanding OUT requests before reset start, successful current-endpoint
  ResetEndpoint/SetTRDequeue commands, and a genuinely new post-reset OUT
  offer and paired success. Fresh post-arm rundown binds the current slot;
  subsequent original full-SHA pairs pass. This supports one narrow recovery
  chain, not prevention or a latency guarantee. Capture quality passes, but
  global analysis quality remains false for eight unmatched startup IN
  cancellations; EOF retains eight IN requests. Natural credit wait and
  exhaustive ordinary-stop continuity remain unqualified. The earlier
  attempt stopped before payload at a
  capture-helper guard; it is neither a driver-traffic failure nor a
  payload pass. Do not transfer `59d64b7`'s native qualification to this binary.
  A separate default-mode0 256 MiB C-file UD/flush/reopen-readback smoke passed
  all five complete SHA checks. Upload receiver pipeline was 225.85 MB/s
  (199.09 MB/s through flush), and download Mac-receiver goodput 333.47 MB/s.
  This short checked pipeline is not a raw physical-disk benchmark,
  long-session qualification or demonstrated throughput improvement.

The [NTB reserved-field correction](NTB-RESERVED-FIELDS.md) in `9d3f3cb`
also passed a 256 MiB C-file UD/readback checksum probe; that was a smoke
check, not a cause determination. Historical tables below belong to
`d7fd6d67a680`, not the current revision.

Historical initial hardware results for `d7fd6d67a680`, on one USB3 connection
(the later [six-run comparison](HARDWARE-AB-20261008.md) supersedes any suggestion
of a stability advantage from this single clean mode-3 run):

| Mode | Result | What it establishes |
| --- | --- | --- |
| `0` | Explicit-source ping and one 64 MiB transfer in each direction passed | Fresh-link smoke check only |
| `1` | Three pairs passed; the next Windows-to-Mac transfer hit OUT `USBD_STATUS_XACT_ERROR`, followed by send timeouts | The initiating failure still reproduces; original failed run retained |
| `3` | 600.42 s, 1100 pairs / 2200 SHA256-checked transfers passed; 68.75 GiB per direction | One sustained healthy run, **not a demonstrated recovery**: no initiating error or recovery event was recorded |

A separate fresh mode-3 pair also passed. The experimental switch was then restored to off, with the original missing registry value restored; the link and explicit-source ping were checked again. Security policies were unchanged, and unrelated computation was not stopped. PR #1 remains unmerged.

Offline ETW correlation from two failed runs found requested/completed lengths of 7924/6144 and 32136/21504 bytes. Those requested lengths also appeared in 1477 and 6399 successful OUT transfers before their respective failures. Neither request was an exact multiple of the 1024-byte maximum packet size. This does not support a failure unique to either length or an exact-MPS request; it does not identify or exclude a link, controller, cable or timing cause. Small IN completions near the errors do not establish heavy bidirectional payload load. No nearby non-bulk stack event was found in the captured windows; absence from this capture does not rule out a link event.

**Scope:** pipe-only recovery addresses the stopped-OUT consequence, not the initiating USB3 bulk-OUT transaction error; that cause is still unknown. Earlier revisions showed transient new completions followed by cooldown/budget failures (the [historical six-run comparison](HARDWARE-AB-20261008.md)). Later finite business passes and positively correlated native recovery chains are progress, not long-term stability, prevention, natural credit-wait or normal Secure Boot qualification.

## Why

A USB3 600 s run on the frozen PR #1 head behaved as follows (evidence in by1907047/1902#2):

1. One bulk-OUT transfer failed with USBD status `0xC0000011` (transaction error) and IRP status `0xC0000001`.
2. After that, no OUT request succeeded. The 128 TX requests only ended as 5 s timeouts.
3. Bulk IN kept completing throughout.

Neither the frozen head nor `v0.1.0-alpha.1` has any bulk-OUT recovery. This experiment tests one hypothesis: resetting only the pipe, without re-enumerating the device, lets OUT traffic progress again after that error.

## Switch

The switch is a `REG_DWORD` named `Sideline1902DataPathDebug` in the device hardware key (`...\Enum\<device instance>\Device Parameters`).

- The driver reads it once, when the device is added. To change it, restart the device.
- Restart with the Mac unlocked. While the Mac is locked, macOS restricts USB.

| Value | Meaning |
| --- | --- |
| missing, `0`, read failure, any unknown bit | Off |
| `1` | OUT instrumentation only |
| `2` | Data-pipe recovery only, with its own logs |
| `3` | Both |

**What still differs from `2327f448cf6c` when the switch is off.**
Off disables experimental recovery/instrumentation; it does not restore
whole-driver equivalence with the older source. Documented differences
include the following:

- **Device add** opens the device hardware key and reads one value. A failed read just selects off.
- **Unknown bits** in the value produce one log line.
- **TX timeouts** are logged as `TX timed out` instead of `TX completion failed`, and counted in their own counter. KMDF reports a request that was cancelled by its own send timer as `STATUS_IO_TIMEOUT`. `TX cancelled` now means `STATUS_CANCELLED` only.
- **Per completion and per send**, the driver classifies the status with plain arithmetic and makes a few mode checks on a constant read once at device add.
- **Code size** grows.
- **Always-on NTB formatting:** [NDP reserved-field initialization](NTB-RESERVED-FIELDS.md) clears the NDP header before assigning its fields, independently of this switch.
- **Always-on RX parsing:** [cyclic NDP header preflight](RX-NDP-CYCLE-HARDENING.md) rejects malformed cycles before delivery, independently of this switch.

When the switch is off, the driver:

- creates no wait lock, work item or timer, and makes no timer calls;
- makes no admission-gate (rundown) calls;
- counts no requests as in flight;
- keeps no timestamps or post-restart markers;
- does not change the readers-failed callback, which still returns `TRUE`.

`out_recovery_probe.py` compiles the frozen head's data-path functions and checks that switch 0 gives the same I/O trace. The modeled trace covers sends, completions, stops, starts, the framework's reader-recovery resets and buffer returns. The same run checks that no lock, rundown or in-flight operation happens. This is a check of the modeled trace, not of timing, code size or every WDF call.

**If the recovery objects cannot be created** (the wait lock, work item or
one-shot timer), recovery stays off, the failure is logged, and device add
continues. No object is enqueued or armed before all allocations succeed.
Instrumentation, if selected, stays on.

## Instrumentation (`0x1`)

Instrumentation records and logs the following. Nothing acts on these values.

- **In flight.** A request counts once it is handed to `WdfRequestSend` and stops counting when it completes. It is counted before the send, because the completion may run inline.
- **Peak in flight, successful completions, and the time of the last OUT success.** Times come from `KeQueryInterruptTime`, which is monotonic, and only differences between them are logged.
- **The first non-cancel failure in each D0 session**, with its status, USBD status, in-flight count, success count and the milliseconds since the last success. This is re-armed after each pipe restart.
- **A summary when TX stops:** `Sideline1902: OUT stop: ...`.

## Recovery (`0x2`)

### Serialization

Every stop, reset and start of either data pipe runs under one PASSIVE-level wait lock, `m_DataPathLock`. That covers:

- queue and D0 start/stop of TX;
- queue and D0 start/stop of RX;
- OUT recovery;
- IN recovery.

The send, completion and readers-failed paths never take this lock. No spin lock is involved anywhere.

The framework's own continuous-reader recovery is the one path that would bypass this lock. KMDF source at `b6191d9`, `FxUsbPipeContinuousReader::FxUsbPipeRequestWorkItemHandler`, shows what it does:

1. It cancels the readers.
2. It calls `EvtUsbTargetPipeReadersFailed`.
3. If the callback returns `TRUE`, it resets the IN pipe, or, if the port is disabled, the whole device (`IOCTL_INTERNAL_USB_RESET_PORT`). It holds no driver lock while doing this.

In recovery mode, `DataBulkInPipeReadersFailed` therefore returns `FALSE`. The framework then does neither reset and does not resubmit the readers. The callback records the failure and enqueues the data-path work item. It takes no lock and does not stop or start the target. This matters because stopping a reader pipe waits for the very work item that runs this callback; `FxUsbPipe::GotoStopState` sets `Wait = TRUE`.

The work item then performs the framework's enabled-port sequence itself, under the lock:

1. `WdfIoTargetStop`, which cancels the readers and waits for the framework work item.
2. `WdfUsbTargetPipeResetSynchronously`, with a 2 s timeout.
3. `WdfIoTargetStart`, which resubmits the readers.

Recovery mode differs from the framework default in two deliberate ways. Both are logged:

- **Port disabled.** The device is never reset. If the pipe reset fails, the readers stay stopped until the next queue or device restart.
- **Device gone.** If the failure status is a device-gone status, nothing is reset.

IN recovery has no budget, which matches the framework default of recovering every time.

The guarantee: in recovery mode, no pipe or port reset by this driver or by the framework on its behalf overlaps another reset, a pipe stop/start, or a queue/D0 transition. Every one of them runs under the lock, or does not run at all.

### OUT trigger

Recovery starts on `USBD_STATUS_XACT_ERROR` from a device that is still present. These never start it:

- cancellations;
- timeouts;
- device-gone statuses: `STATUS_NO_SUCH_DEVICE`, `STATUS_DEVICE_NOT_CONNECTED`, `STATUS_DEVICE_REMOVED`, `STATUS_DELETE_PENDING`, `STATUS_DEVICE_DOES_NOT_EXIST`, `STATUS_DEVICE_POWERED_OFF`, and USBD `DEVICE_GONE`;
- stall, babble, and every other status.

Every status is still counted and logged.

### OUT sequence (work item, under the lock)

1. **Decide.** The work item skips, with a log line, if recovery is stopped
   or the pipe is not running. A fault within the 10 s cooldown or waiting
   for time credit remains pending until both conditions permit an attempt.
2. **Close admission and drain.** `TransmitFrames` holds a rundown reference for its whole send section, at up to DISPATCH_LEVEL. `ExWaitForRundownProtectionRelease` refuses new sends and waits for sends already in progress. This step exists because a stopped KMDF target queues new sends (`STATUS_WDF_QUEUED`) instead of failing them, and no send may reach a pipe that is being reset.
3. **Stop.** `WdfIoTargetStop(CancelSentIo)` returns after every sent request's completion routine has run.
4. **Reset.** `WdfUsbTargetPipeResetSynchronously` issues `URB_FUNCTION_SYNC_RESET_PIPE_AND_CLEAR_STALL` with a 2 s timeout.
5. **Restart.** Only if the reset succeeded, call `WdfIoTargetStart`. Only if
   that start succeeded, mark the pipe running, set the post-restart markers
   and consume the old pending fault **before** reopening admission. There
   is no trailing clear after reopening: a new completion may already have
   recorded another fault while the original callback is returning.

The log label after a successful start is `pipe restarted, data recovery unverified`, because a successful API call is not delivery. If the reset or the start fails, the failure is logged and kept: the pipe is not running, and sends are refused instead of being queued. Only a normal queue restart or device restart reopens the pipe.

Recovery never resets or cycles the port, never resets the device and never
retries a payload. A one-shot timer only delivers an actual fault retained
during cooldown or token wait; it is not periodic polling or an automatic retry after a
failed reset/start.

**Budget.** Capacity three tokens, one token per experimental 60 s, and at
least 10 s between attempt starts (before drain, not a physical USB reset
spacing guarantee). These are conservative experiment parameters, not
measured optimal values or a prevention claim.

- A new D0 session initializes a full bucket. A queue restart does not refill
  it directly; elapsed interrupt time still accrues while idle or stopped.
- Credit is continuous in 100 ns units, saturates at three tokens and is
  debited only when an actual attempt starts, including a failed attempt.
  The 64-bit lifetime attempt counter is diagnostic, never a gate.
- An error while the pipe is not running is terminal and logged. An empty
  bucket never discards an authentic pending fault.
- A single-shot timer expires after the later of the remaining cooldown and
  next-token wait, then enqueues the existing work item. The work item
  checks lifecycle, credit and time again under the data-path lock. This
  works even if subsequent completions only time out. An early timer
  delivery is rearmed for the remaining time, not a new full period.
- Errors while a fault is queued, deferred or recovering are coalesced.
  Neither a timeout nor an arbitrary successful completion consumes that
  pending fault. A successful completion may belong to old/out-of-order I/O.
- Admission and pipe state are unchanged while deferred. Further
  sends/timeouts can therefore occur until the remembered recovery runs;
  the fixed request pool still bounds outstanding requests. This revision
  does not implement TX backpressure or change queue/drop behavior.
- Within a continuous D0 session, any interval of length L permits at most
  three plus ceil(L / 60 s) attempts; the ten-second attempt spacing also
  applies. Saturation cannot bank additional idle credit. The existing
  timer/stop drains and IN/OUT reset ownership are unchanged.
- Residual risks: an empty bucket may leave a halted pipe waiting up to
  about a minute, so a TCP/application flow can fail before eventual recovery.
  If reset/start APIs repeatedly succeed without useful data, infrequent
  resets may continue indefinitely at the bounded rate. There is no new
  sustained-progress circuit breaker, no payload replay and no prevention fix.

**Offered traffic.** After a restart, the driver logs two events:

- `OUT first send offered after pipe restart: +N ms` when the first new send is handed to `WdfRequestSend`;
- `OUT first success after pipe restart: +N ms after restart, +M ms after the first send offered after it`.

Every request sent before the restart was cancelled by its stop, so these refer only to new traffic. The restart's own phase durations (drain, stop, reset, start) are logged separately.

The first-send timestamp is published by one 64-bit compare/exchange, before
calling `WdfRequestSend`. There is no separate claimed flag: an inline
completion from a competing sender must not see a claimed but unpublished
timestamp. A controlled two-sender test covers that preemption. The marker is
a driver offer-time observation, not the USB bus submission time; use ETW to
cross-check the data-progress window.

### Lifecycle

`StopTransmit` is the path used by `NcmTxQueue::Stop`, D0Exit (through `LeaveWorkingState`) and adapter destroy. It does the following:

1. Clears the running flag.
2. Closes admission.
3. Stops the pipe.
4. Drains the one-shot timer with `WdfTimerStop(TRUE)` and clears the pending
   fault while still holding the data-path lock. Recovery was atomically
   disabled before step 1, so the timer cannot establish new live work.
5. Releases the lock.
6. Flushes the work item. The flush must come after the lock is released,
   because the work item needs the lock. It runs even when there is no pipe.

The timer uses a nonblocking DPC callback with automatic serialization
disabled. It only reads the atomic enabled/pending flags and enqueues work;
it never takes the data-path lock or waits. Thus draining the timer while
holding that lock does not wait on a callback which needs the lock. Duplicate
stops are serialized by the lock; work-item flush remains outside it. A DPC
which checked enabled immediately before stop may still enqueue, but the
timer drain waits for that enqueue and the following flush consumes it.
The stopped worker cannot rearm the timer. Normal successful queue start
reenables recovery before reopening admission.

After that flush nothing can enqueue the work item:

- **OUT side.** The stop completed every completion routine, and admission is closed.
- **Timer side.** Recovery is disabled and the synchronous timer drain
  completed every timer callback, including a late work-item enqueue.
- **IN side.** `StopReceive` stopped the reader pipe first. That stop waits for the framework reader work item, and the framework queues no new one while the pipe is stopped.

D0Entry re-selects the alternate setting and fetches new pipe handles only after that. The work item reads a pipe only under the lock, and only while that pipe is marked running.

### Time bounds and assumptions

- **Reset requests.** These are the only steps with a time bound: 2 s each.
- **Drain.** It waits for send sections, which do not block.
- **Stops.** They wait for the USB stack to complete the cancelled requests, as the existing stops do.
- **Waiting behind recovery.** A queue stop or D0Exit that arrives during a recovery waits for that recovery to finish. Phase durations are logged so this wait can be measured. No hard bound is claimed for the whole work item.

## Portable tests (Linux)

Run `python3 tests/out_recovery_probe.py`. It also runs as part of `tools/run_portable_tests.py`.

The probe compiles the production functions and class. It runs them against a KMDF model under ASan, UBSan and real threads. The model includes:

- stopped-target queuing;
- inline completion;
- a stop that waits for completions and for the reader work item;
- the framework's reader recovery, which on `TRUE` resets the pipe, or the port when the port is disabled, without any driver lock.

The probe covers:

- each switch value, including recovery without instrumentation;
- allocation failures;
- the off state: no lock, gate or in-flight use, and the same I/O trace as the frozen head;
- status classification;
- admission racing the drain, and sends during a reset;
- buffer ownership;
- failed reset and failed start;
- time credit and cooldown, D0 reset versus queue persistence, timestamp zero,
  unsigned wrap and saturating long-idle refill;
- more than three recoveries in one modeled D0, the observed Trial2 fault
  sequence followed by dense token wait, and new sends/successes after each;
- a cooldown fault followed only by timeouts, duplicate coalescing, an old
  success which must not erase the fault, and an early timer delivery;
- inline/fast fresh XACT_ERROR between admission reopening and the original
  callback returning, including a second callback waiting on the lock;
- deferred stop/D0Exit and a new D0 session without timer resurrection,
  concurrent stops, and timer DPCs paused before their enabled check and
  immediately before a late enqueue;
- races between the work item and stop, D0Exit or a null pipe;
- IN recovery: the `FALSE` handover, a disabled port, a failed reset, device gone, and a stop that comes first;
- an IN/OUT/D0Exit race on threads, 150 rounds, checking that resets never overlap;
- a continuous reader-failure storm followed by D0Exit, requiring the modeled
  callbacks and queued work to quiesce (not a bound on real USB cancellation);
- a first-send marker publication race with a competing inline completion;
- a threaded stress run.

**Limits.** These tests cannot show KMDF scheduling, IRQL or paging rules, Driver Verifier results, USB hardware behavior, or whether a pipe reset restores Apple's device-mode endpoint. The framework is modeled from its source, not executed. `NcmTxQueue::Advance` is mirrored, not run. The WDK constants and annotations are checked only by a WDK build.

## Hardware acceptance (owner's local decision)

Run with circular USB ETW and DebugView and the existing harness unchanged.
Record actual lock/lid/power state; do not silently change accessory security.
The harness stops on the first failed pair. That pair and that run stay failed
and are never converted to a pass. DebugView buffering can hide live markers:
online "not seen" is not evidence of absence; inspect the flushed log and ETW.

**R0: switch absent.** A short smoke test with the candidate build:

- link and MTU are correct;
- ping succeeds 3/3;
- no `OUT `, `IN ` or `data-path` log lines appear.

**R1: switch `3` (or `2`).** USB3 600 s, at most 3 runs. Stop after the first run in which `OUT recovery ... start` appears.

- **Recovery never starts.** The result is inconclusive.
- **Recovery starts.** Record the restart log line (reset/start status and phase durations) as the API result only. Then run a separate, bounded post-restart probe:
  - It runs on the same USB attachment. ETW must show no PnP removal and no re-enumeration.
  - It does not retry the failed payload.
  - It offers new traffic: ping 3/3 and one fresh 64 MiB checked pair.
  - Its first send time is where data progress starts to be measured. The driver's `OUT first send offered after pipe restart` line and ETW mark it.
  - Report it as "post-restart probe", separately from the sustained run.

**Data progress after the restart is supported if all of these hold:**

- an OUT completion succeeds within 1 s of that first offered send;
- the post-restart probe passes;
- ETW shows no PnP removal and no hub port reset or warm reset for the device;
- attempts obey the renewable credit and ten-second attempt-start interval;
- separately qualify more than three successful recovery epochs in one D0,
  and a token-wait episode delivered without another XACT. If those cases do
  not occur naturally, native coverage is incomplete despite portable tests.

**Data progress is refuted if any of these happen:**

- no OUT completion succeeds within 5 s of the first offered send;
- the reset fails or times out;
- the error recurs and fresh checked traffic still cannot progress;
- the post-restart probe fails.

If no traffic was offered after the restart, there is no conclusion either way.

**Stop and roll back on any of these:**

- a bugcheck;
- a stop that hangs longer than 30 s;
- any port reset or cycle attributable to the driver;
- an attempt outside the capped refill/cooldown policy, a lost pending fault,
  or a failed reset/start followed by an automatic API retry.

To roll back, delete the value or set it to 0, then restart the device. If that is not enough, reinstall the frozen build.

Driver Verifier is not required by this document; enabling it is the owner's choice.
