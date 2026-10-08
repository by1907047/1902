# Experimental bulk-OUT diagnostics and pipe-only recovery

Status: **experimental, off by default, source only.** Not built with the WDK, not installed and not hardware-tested. Nothing here changes behavior unless the switch below is set. The USB3 transaction error that starts the sustained-traffic stall still has an unknown cause, and this code does not address that cause.

## Why

A USB3 600 s run on the frozen PR #1 head showed this sequence (evidence in by1907047/1902#2):

1. One bulk-OUT transaction error: USBD `0xC0000011`, IRP `0xC0000001`.
2. After that, no successful OUT completion. The 128 TX requests only ended as 5 s timeouts.
3. Bulk IN kept completing throughout.

The driver has no bulk-OUT pipe recovery, and neither does `v0.1.0-alpha.1`. This experiment tests one hypothesis: a pipe-only reset, with no re-enumeration, restores OUT progress after that error.

## Switch

Set a `REG_DWORD` named `Sideline1902DataPathDebug` in the device's hardware key, `...\Enum\<device instance>\Device Parameters`. The driver reads it once when the device is added, so a change takes effect only after the device restarts. Restart with the Mac unlocked; while it is locked, macOS restricts USB.

| Value | Meaning |
| --- | --- |
| missing, `0`, read failure, any unknown bit | Off. The TX I/O sequence is identical to `2327f448cf6c`. The only log change is that send timeouts are now labelled `TX timed out` instead of `TX completion failed`. |
| `1` | OUT instrumentation only. |
| `2` | OUT pipe recovery only, with its own logs. |
| `3` | Both. |

**Instrumentation (`0x1`)** records these values and logs them; nothing acts on them:

- Peak requests in flight.
- Successful completions.
- Time of the last OUT success, from `KeQueryInterruptTime`, which is monotonic.
- The first failure in each D0 session. This is re-armed after a successful recovery. It logs the status, the USBD status, the in-flight count and the milliseconds since the last success.
- A summary when transmit stops: `Sideline1902: OUT stop: ...`.

**Counted in every mode**, including 0:

- `TX cancelled (stop or cancel)`: `STATUS_CANCELLED`.
- `TX timed out (5 s send timeout)`: KMDF reports a request cancelled by its own timer as `STATUS_IO_TIMEOUT`.
- `TX completion failed`: everything else.
- Send failures.

## Recovery trigger

The trigger is a TX completion whose USBD status is `USBD_STATUS_XACT_ERROR`, unless the completion status shows that the device is gone. These never trigger recovery:

- Cancellations and timeouts.
- Device-gone statuses: `STATUS_NO_SUCH_DEVICE`, `STATUS_DEVICE_NOT_CONNECTED`, `STATUS_DEVICE_REMOVED`, `STATUS_DELETE_PENDING`, `STATUS_DEVICE_DOES_NOT_EXIST`, `STATUS_DEVICE_POWERED_OFF`, and USBD `DEVICE_GONE`.
- Stall, babble, and every other status.

All statuses are still counted and logged.

## Sequence

The recovery runs in a work item at `PASSIVE_LEVEL` and holds the TX lifecycle wait lock throughout:

1. **Decide.** Skip with a log line if the pipe is not running, the budget is used up, or the 10 s cooldown has not passed.
2. **Close admission and drain.** `ExWaitForRundownProtectionRelease` makes new `TransmitFrames` calls fail at once. It then waits for every send section that is already inside `WdfRequestSend`.
3. **Stop the target.** `WdfIoTargetStop(CancelSentIo)` returns after every sent request's completion routine has run. All buffers are back in the pool.
4. **Reset the pipe.** `WdfUsbTargetPipeResetSynchronously` issues `URB_FUNCTION_SYNC_RESET_PIPE_AND_CLEAR_STALL`, with a 2 s request timeout.
5. **Restart.** Only if the reset succeeded, call `WdfIoTargetStart`. Only if that start succeeded, mark the pipe running and reopen admission.

If the reset or the start fails, the failure is logged and kept: the pipe stays not running and admission stays closed. Sends are refused and dropped instead of being queued to a stopped target. Only a normal queue restart or device restart reopens it.

The recovery never resets or cycles the port, never resets the device, and never retries a payload. There is no timer and no retry loop.

## Budget and cooldown

- The budget is 3 attempts per D0 session. It resets in `EnterWorkingState` (D0Entry), not on a queue restart.
- Attempts must be at least 10 s apart.
- An error that arrives during the cooldown, after the budget is used up, or while the pipe is not running is counted and logged as skipped, on the 1st, 2nd, 4th... occurrence, and is not acted on later.
- An error that arrives while a recovery is already queued or running is counted as coalesced.

## Synchronization

- **Send path, up to `DISPATCH_LEVEL`.** `TransmitFrames` holds a rundown reference for its whole send section. Before `WdfRequestSend` it increments the in-flight count. On a FALSE return it undoes that increment, because the completion routine does not run. After a TRUE return it does not touch the request, because an inline completion may already have returned the buffer to the pool.
- **Completion path.** It uses only interlocked operations and may enqueue the work item. It never takes the wait lock. No spin lock is held across a blocking call or across an inline completion.
- **Who changes admission and target state.** Only `StartTransmit`, `StopTransmit` and the recovery work item. All three run at `PASSIVE_LEVEL` under the wait lock.
- **What `StopTransmit` does.** This is the path that `NcmTxQueue::Stop`, D0Exit through `LeaveWorkingState`, and adapter destroy all use:
  1. Clears the running flag.
  2. In recovery mode, closes admission.
  3. Stops the pipe.
  4. Releases the lock, and only then calls `WdfWorkItemFlush`.

  The work item needs the lock, so flushing while holding it would deadlock. The flush also runs when there is no pipe.
- **Why nothing enqueues after that flush.** `WdfIoTargetStop` has returned after every completion routine, and admission is closed, so no new send can produce a completion until the next `StartTransmit`.
- **Why no stale pipe handle is used.** D0Entry re-selects the alternate setting and gets new pipe handles, but that happens only after D0Exit has run `StopTransmit` and the flush. The work item reads the pipe only under the lock, and only while the pipe is marked running.

**Assumptions.** Only the reset request has a time bound, 2 s. The drain waits for send sections, which do not block. The stop waits for the USB stack to complete cancelled requests, exactly as `StopTransmit` already did. A `StopTransmit` that arrives during a recovery therefore waits for the drain, the cancellation, at most 2 s of reset, and the start. Every recovery logs these phase durations: `drain`, `stop`, `reset` and `start`, in milliseconds.

## Portable tests (Linux)

Run `python3 tests/out_recovery_probe.py`. It runs as part of `tools/run_portable_tests.py`.

The probe compiles the production functions from `host/device.cpp` and the production class from `host/device.h`. It runs them against a KMDF model under ASan, UBSan and real threads. The model follows the open-source KMDF framework in these points:

- A stopped target queues new sends.
- A stop with `CancelSentIo` returns only after the completion routines have run.
- A completion may run inline.
- A send that returns FALSE gets no completion.

The probe covers:

- Every switch value.
- Classification of each status.
- Stopped-target queuing, with and without admission control.
- A sender that races with the drain.
- Senders during a reset.
- Inline completion, a FALSE send, and a format failure.
- Failed reset and failed start.
- Budget and cooldown.
- A queue restart compared with a new D0 session.
- Races between the work item and stop, D0Exit, or a missing pipe.
- A threaded stress run.

It also compiles the TX functions of the frozen `2327f448cf6c` head and requires switch 0 to produce an identical I/O trace.

Eleven deliberate mutations of `device.cpp` were each caught during development, for example removing the drain, flushing inside the lock, or reopening after a failed start.

**Limits.** Linux shims cannot show KMDF scheduling, IRQL or paging rules, Driver Verifier results, or USB hardware behavior. `NcmTxQueue::Advance`'s caller contract is mirrored, not executed. The WDK constants are checked by `static_assert` only in a real WDK build.

## Hardware acceptance (owner's local decision)

These criteria are for the owner's local runs. Use circular USB ETW and DebugView, keep the Mac unlocked, and use the existing harness unchanged. That harness stops on a failed pair: a failed pair stays failed, and a failed sustained run is never converted to a pass.

**R0: switch absent.** Run a short smoke test on the candidate build:

- link, address and MTU are correct;
- ping 3/3;
- no `OUT ` or `data-path` log lines.

This shows that "off" behaves like the frozen head. It is not a regression proof under load.

**R1: switch `3`, or `2` to exclude instrumentation effects.** Run USB3 600 s, up to 3 runs, and stop after the first run in which recovery starts.

- **Not triggered.** No `OUT recovery ... start` line appears. This is inconclusive, not a pass.
- **Triggered.** Keep the original failed pair as failed. Then, as a separately labelled post-recovery check on the same connection, with no re-enumeration and no payload retry, run ping 3/3 and one fresh bounded 64 MiB pair.

  The hypothesis is **supported** if all of these hold:
  - the reset status is success;
  - ETW shows a successful OUT completion within 1 s of the restart;
  - the post-recovery check passes;
  - ETW shows no PnP removal and no hub port reset or warm reset for the device;
  - there are at most 3 attempts.

  The hypothesis is **refuted** if any of these happen:
  - the reset succeeds but no OUT completion succeeds within 5 s;
  - the reset fails or times out;
  - the error recurs within the cooldown or until the budget is used up;
  - the post-recovery check fails.

**Stop and roll back** on any of the following:

- a bugcheck;
- a stop that hangs for more than 30 s;
- any port reset or cycle attributable to the driver;
- more than 3 attempts in one D0 session.

To roll back, delete the value or set it to 0, then restart the device, or reinstall the frozen build.

Driver Verifier is not required by this document. Enabling it is the owner's choice.
