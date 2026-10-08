# Experimental data-pipe diagnostics and pipe-only recovery

**Status:** experimental; this PR publishes source only, not a driver binary. Commit `d7fd6d67a680` passed offline x64 Debug/Release WDK builds and both INF validations, and its locally test-signed Release was installed for hardware tests on 2026-10-08. It is not Microsoft-signed. Existing native-analysis/dependency warnings remain.

**2026-10-09 source revision:** a cooldown fault is now retained for one
deferred attempt, and a new fault after admission reopens cannot be erased by
the preceding recovery callback. This revision is default-off and is not yet
WDK-built or hardware-qualified. The historical results below belong to
`d7fd6d67a680`, not this revision. It addresses two recovery-state defects,
not the cause of the first USB3 transaction error.

Initial hardware results for that exact driver commit, on one USB3 connection
(the later [six-run comparison](HARDWARE-AB-20261008.md) supersedes any suggestion
of a stability advantage from this single clean mode-3 run):

| Mode | Result | What it establishes |
| --- | --- | --- |
| `0` | Explicit-source ping and one 64 MiB transfer in each direction passed | Fresh-link smoke check only |
| `1` | Three pairs passed; the next Windows-to-Mac transfer hit OUT `USBD_STATUS_XACT_ERROR`, followed by send timeouts | The initiating failure still reproduces; original failed run retained |
| `3` | 600.42 s, 1100 pairs / 2200 SHA256-checked transfers passed; 68.75 GiB per direction | One sustained healthy run, **not a demonstrated recovery**: no initiating error or recovery event was recorded |

A separate fresh mode-3 pair also passed. The experimental switch was then restored to off, with the original missing registry value restored; the link and explicit-source ping were checked again. Security policies were unchanged, and unrelated computation was not stopped. PR #1 remains unmerged.

Offline ETW correlation from two failed runs found requested/completed lengths of 7924/6144 and 32136/21504 bytes. Those requested lengths also appeared in 1477 and 6399 successful OUT transfers before their respective failures. Neither request was an exact multiple of the 1024-byte maximum packet size. This does not support a failure unique to either length or an exact-MPS request; it does not identify or exclude a link, controller, cable or timing cause. Small IN completions near the errors do not establish heavy bidirectional payload load. No nearby non-bulk stack event was found in the captured windows; absence from this capture does not rule out a link event.

**Scope:** recovery only restarts a halted pipe. It does not address whatever causes the first USB3 bulk-OUT transaction error, and that cause is still unknown. Later hardware tests showed transient new OUT completions after restart, but repeat errors during cooldown left transfers timing out. Durable end-to-end recovery acceptance remains incomplete; see the [six-run comparison](HARDWARE-AB-20261008.md).

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

**What still differs from `2327f448cf6c` when the switch is off.** It is not "nothing", so the full list:

- **Device add** opens the device hardware key and reads one value. A failed read just selects off.
- **Unknown bits** in the value produce one log line.
- **TX timeouts** are logged as `TX timed out` instead of `TX completion failed`, and counted in their own counter. KMDF reports a request that was cancelled by its own send timer as `STATUS_IO_TIMEOUT`. `TX cancelled` now means `STATUS_CANCELLED` only.
- **Per completion and per send**, the driver classifies the status with plain arithmetic and makes a few mode checks on a constant read once at device add.
- **Code size** grows.

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

1. **Decide.** The work item skips, with a log line, if recovery is stopped,
   the pipe is not running or the budget is used up. A fault within the 10 s
   cooldown is retained and delivered once at the cooldown deadline.
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
during cooldown; it is not periodic polling or an automatic retry after a
failed reset/start.

**Budget.** 3 attempts per D0 session, at least 10 s apart.

- The budget resets in `EnterWorkingState` (D0Entry), not on a queue restart.
- An error after the budget is used up or while the pipe is not running is
  counted and logged as skipped (1st, 2nd, 4th... occurrence).
- An error during cooldown remains pending. A single-shot timer expires at
  `lastAttempt + 10 s`, then enqueues the existing work item. The work item
  checks lifecycle, budget and time again under the data-path lock. This
  works even if subsequent completions only time out. An early timer
  delivery is rearmed for the remaining time, not a new full cooldown.
- Errors while a fault is queued, deferred or recovering are coalesced.
  Neither a timeout nor an arbitrary successful completion consumes that
  pending fault. A successful completion may belong to old/out-of-order I/O.
- Admission and pipe state are unchanged while cooldown is pending. Further
  sends/timeouts can therefore occur until the remembered recovery runs;
  the fixed request pool still bounds outstanding requests. This revision
  does not implement TX backpressure or change queue/drop behavior.

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
- budget and cooldown, and the D0-session versus queue-restart budget;
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

Run with circular USB ETW and DebugView, the Mac unlocked, and the existing harness unchanged. The harness stops on the first failed pair. That pair and that run stay failed and are never converted to a pass.

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
- there are at most 3 attempts.

**Data progress is refuted if any of these happen:**

- no OUT completion succeeds within 5 s of the first offered send;
- the reset fails or times out;
- the error recurs until the budget is used up;
- the post-restart probe fails.

If no traffic was offered after the restart, there is no conclusion either way.

**Stop and roll back on any of these:**

- a bugcheck;
- a stop that hangs longer than 30 s;
- any port reset or cycle attributable to the driver;
- more than 3 OUT attempts in one D0 session.

To roll back, delete the value or set it to 0, then restart the device. If that is not enough, reinstall the frozen build.

Driver Verifier is not required by this document; enabling it is the owner's choice.
