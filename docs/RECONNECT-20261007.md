# PR #1 native reconnect test and delayed recovery

This is a sanitized laboratory report, not a driver fix or a hardware approval.
It supplements [PR #1](https://github.com/by1907047/1902/pull/1).
Raw traces, device serials, interface GUIDs, local usernames, management addresses,
binaries and signing material remain private. This documentation PR does not
change the tested source or either source-snapshot manifest.

## Tested identity and environment

- Source: `2327f448cf6c755d864fdb795ad6f6a961efe3df`, the frozen PR #1 head.
- Installed test SYS SHA256:
  `2C911E6CACDB07B8AFB6079608A498307E248C4B05835533DD509B021B3C2B22`.
- Local published INF identifier: `oem60.inf` (machine-specific, not an installer contract).
- MacBook Pro M1; Windows 11 x64 build 26200 on Dell Precision 7920.
- HVCI enabled; Secure Boot disabled; test signing enabled. No claim of
  production signing or Secure Boot compatibility.
- Direct Apple USB NCM device `VID_05AC&PID_1902`; independent Ethernet management.
- Intended USB IPv4 link: private /30 subnet, MTU 8000 on both endpoints.
- Native Debug/Release builds completed with zero errors and 70/68 warnings;
  InfVerif and portable tests passed. These are build checks, not qualification.

No driver source/binary, boot policy, route, MTU or calculation job was changed
during the reconnect experiment or passive follow-up. No throughput benchmark
was run during the recovery watch. Cable-only comparisons are not established.

## Single PnP restart: failed bounded acceptance test

Exactly one `pnputil /restart-device` request targeted the exact USB parent
instance. The tool returned 0 after 2.323 seconds. A successful tool exit is not
evidence that the device restarted into a usable state.

All 268 Windows observations from 2.603 to 599.713 seconds found the parent and
network adapter absent. The 600-second observation window expired without
recovery. The Mac timeline contains 311 samples: the USB interface transitioned
from active to inactive and lost its USB IPv4 address, with no recovery through
the end of that recording. The Windows driver service was Stopped. Independent
management Ethernet stayed available, and Windows had no default routes.

There was no subsequent device restart, enable/disable, rescan, reinstall or
traffic probe during this bounded observation. No cable or lid operation was
requested as part of it. Earlier numbered preparation attempts failed before
the hardware restart; they are not additional restart trials.

### Native kernel capture

Official Microsoft-signed DebugView CLI 5.02 captured these four driver messages.
Timestamps are relative to this capture's start, not cross-machine wall time:

```text
3.586882 USBNCM: D0Exit to state 5
3.823962 USBNCM: Idle power management disabled
3.825346 USBNCM: WdfUsbTargetDeviceCreateWithParameters FAILED 0xC000000E
3.825352 USBNCM: InitializeDevice failed 0xC000000E
```

`0xC000000E` is `STATUS_NO_SUCH_DEVICE` according to the
[Microsoft NTSTATUS reference](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55).
In the frozen source, `host/device.cpp::InitializeDevice` returns immediately
after USB-target creation fails, before descriptor/interface parsing,
configuration selection, alternate-setting selection, NTB negotiation or
packet-transfer initialization. This identifies the first captured failure
boundary; it does not identify which component caused the device disappearance.

The Mac's local kernel sequence was:

```text
15:47:22.510 controller On -> Suspended; USB suspend
15:47:22.537 controller Suspended -> On
15:47:22.657 USB device address set to 35
15:47:22.664 controller On -> Off
```

The primary NCM registry snapshot showed `HostAttached=0`, `IOLinkStatus=1`.
Windows and Mac wall clocks differ by about one minute. Do not directly subtract
their timestamps or infer a sub-second causal ordering between platforms.

## Passive follow-up: eventual recovery verified

The user chose a detached local recorder instead of recurring chat tasks.
The former heartbeat was deleted. The recorder sampled the Mac every two
seconds and made bounded, read-only Windows queries every 30 seconds, with a
55-second outer query timeout. It did not reset, rescan, reinstall, change power
settings or request a cable operation. It was configured to stop upon verified
recovery or at the original deadline, 2026-10-07 12:01:01 UTC.

The recorder started at 08:15:09.120 UTC (Mac clock) and stopped automatically
after confirming recovery at 08:16:58.472 UTC, before that deadline:

| Observation | Mac-recorder timestamp (UTC) |
| --- | --- |
| Last Windows observation not ready | 08:16:15.815 |
| First Windows observation ready | 08:16:48.118 |
| Second ready observation completed | 08:16:55.352 |
| USB-specific route and ping verification complete | 08:16:58.472 |

These are recorder observation timestamps, not exact Windows transition times.
The Windows readiness transition is bracketed between the last not-ready and
first ready observations; query latency and polling limit the precision. Do not
interpret the recorder's roughly 109-second lifetime as the total time since
the earlier PnP restart. The follow-up is separate from the failed 600-second
test and does not retroactively turn that test into a pass.

Recovery checks found:

- Exact USB parent present with PnP status OK; corresponding network adapter
  connected; `SidelineAppleNcm1902` Running.
- The active service's SYS path hashed to the tested SHA256, not just a cached INF.
- Intended Windows USB IPv4 address Preferred and IPv4 MTU 8000.
- Mac USB interface active with the intended /30 IPv4 address and MTU 8000.
- Independent management remained available; Windows default-route count zero.
- A scoped route resolved to the USB interface. Three source-bound USB pings
  returned successfully: 0% loss, RTT 4.954 / 1.831 / 1.551 ms.

This verifies a usable USB link at the follow-up check. It does not establish
why the link recovered, a repeatable recovery time, long-term stability, upload
performance, a hardware speed-class change or production signing. No corrective
action by this test harness explains the recovery; outside activity was not
instrumented sufficiently to exclude every external cause.

## Second actual restart: recovery with a transient enumeration failure

The next actual single restart used the same frozen source and installed SYS.
This was not a new driver or a repair. A preliminary ETW preparation attempt
stopped before restarting the device because its inner script was missing at
the expected location; that preparation failure is not a restart trial.

USBXHCI, UCX, USBHUB3 and Kernel-PnP ETW were running before the actual restart,
alongside native DebugView and a one-second Mac state/kernel-log recorder.
The PnP tool returned 0 after 2.299 seconds. The first complete Windows-ready
observation was 23.088 seconds after the restart request; subsequent checks
were also ready. The capture ended normally. Independent management stayed
available and Windows default-route count remained zero. Other calculation
jobs were left running, as explicitly authorized by the user.

```text
3.603556 USBNCM: D0Exit to state 5
3.815350 USBNCM: Idle power management disabled
3.816132 USBNCM: WdfUsbTargetDeviceCreateWithParameters FAILED 0xC000000E
3.816134 USBNCM: InitializeDevice failed 0xC000000E
19.356536 USBNCM: Idle power management disabled
19.360708 USBNCM: InitializeDevice SUCCESS
19.374552 USBNCM: D0Entry from state 5
19.374580 USBNCM: Link speed 5000000000 bps
```

These are DebugView capture-relative times, not time since restart. The 23.088
seconds above is the readiness observation, not an exact link transition.

The ETL contained 8025 events and reported zero events lost. `tracerpt` decoded
the trace with one schema warning on a SystemTrace metadata header, not a
zero-warning decode. Raw ETL/XML remain private. The target was on the Intel
xHCI controller `8086:A1AF`, root-hub port 17. The target device identity was
matched using descriptor/rundown data and its old/new USB object association.
Rundown records must not be mistaken for live disconnect events.

The following sequence uses only the Windows trace's own clock. Its rendered
timezone offset is inconsistent with the external UTC query timestamps; do
not normalize it against the Mac clock or infer cross-machine millisecond order.

| Windows trace time | Target-port observation |
| --- | --- |
| 16:37:04.783 | PortStatus `0x203` |
| 16:37:04.806 | USBHUB3 event 123, "Failure during Port Change Request": previous `0x203`, current `0x2C0`, change `0x41`, event `0xBF5` |
| 16:37:04.877 | Another event 123: previous `0x2C0`, current `0x2A0`, change `0x30`, event `0xBC9` |
| 16:37:04.878 | Old USB object deleted |
| 16:37:20.142 | PortStatus `0x203`, change `1`; enumeration starts on a new USB object |
| 16:37:20.156 | Enumeration completes, NTSTATUS `0` |
| 16:37:20.366 | PrepareHardware on the new object |

Before the port-status failure, descriptor reads and control requests with
`bRequest=0x31,wValue=0x28` and `bRequest=0x30` completed successfully. A separate
xHCI ConfigureEndpoint event showed configuration 1/interface **0**/alternate
0. That is not evidence that NCM data interface **1** was explicitly switched
to alternate 0 by this driver. Numeric port-state/internal hub-event decoding
and causal attribution require further review.

The Mac's own local log first records On → Suspended → On and a USB reset.
About 15 seconds later it records `cableChangeOccurred: cable connected,
powering on USB3 + USB2`, Off → On, a new device address and configuration 1.
The live stream did not contain the preceding On → Off message; sampled NCM
state and the subsequent Off → On still showed an interruption. This OS cable
notification is not proof of a human unplug/replug. The test harness made no
cable operation, and outside activity was not comprehensively instrumented.

Afterward, both endpoints had the intended /30 USB addresses, MTU 8000, the
expected running driver and a connected adapter. Mac route lookup resolved to
the USB interface, and three pings bound to the USB source address succeeded:
0% loss, RTT 4.980 / 1.691 / 1.994 ms. The Windows driver reported 5 Gbps; no
throughput or long-term stability claim follows from that link-speed field.

This run demonstrates short automatic recovery after the same initial failure,
not a fixed reconnect problem. It does not erase the first trial's failed
600-second acceptance result. The variability is now a key test requirement.

## Split disable/hold/enable experiment

### Port-state definitions cross-check

The numeric decoding was cross-checked against Microsoft's public
[usbspec.h definitions](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/shared/usbspec.h),
not merely a recollection or internal hub-state-machine label. USB3 connection
and enabled flags occupy bits 0/1, the link-state field occupies bits 5–8, and
port power is bit 9. Therefore `0x203` is connected/enabled/U0/powered;
`0x2C0` is disconnected/disabled/Inactive/powered; and `0x2A0` is
disconnected/disabled/Rx.Detect/powered. Change `0x41` combines connection and
link-state changes; `0x30` combines ordinary reset and BH reset changes.
Requests `0x30` and `0x31` correspond to SET_SEL and ISOCH_DELAY. This decoding
does not identify the actor that triggered those transitions or explain the
internal hub event numbers `0xBF5` / `0xBC9`.

### Recorded result

One targeted disable completed with exit 0, followed by a 29.998-second hold
and one targeted enable with exit 0. This is **not** another restart trial and
is not a driver change. The first complete Windows-ready observation was
5.332 seconds after the enable request, with further ready checks. Post-test
USB-source ping passed 3/3. The same SYS, /30 addresses and MTU 8000 were verified.

```text
3.603937 USBNCM: D0Exit to state 5
33.922592 USBNCM: Idle power management disabled
33.930523 USBNCM: InitializeDevice SUCCESS
33.945607 USBNCM: D0Entry from state 5
33.945617 USBNCM: Link speed 5000000000 bps
```

No `STATUS_NO_SUCH_DEVICE` was captured. All 63 one-second Mac observations
reported active USB link and the intended address. The live Mac stream captured
a USB reset and configuration 0 → 1 near enable; it contained no suspend,
On/Off transition or cable-change message. Sampling/logging cannot rule out
every short unobserved transition.

ETW reported 5812 events, zero lost and the same single metadata schema warning.
Target port 17 had two live status records near enable: `0x203/change=0x30`,
then `0x203/change=0`. No target-port event 123 or new USB-object create/delete
was found in this trace. xHCI device update retained the same USB object,
with a changed slot identifier; data interface 1/alternate 1 configuration
completed with status 0.

No direct port-status observation was captured during the hold. Thus this is
not proof of a sustained U3 state or an isolated suspend experiment. It shows
that this one disable/hold/enable run behaved differently from both direct
restart trials. API path and hold duration are confounded; an immediate-enable
control is needed before assigning the improvement to either.

## Short post-recovery traffic checks

The same candidate then passed a 64 MiB upload to a real file on the Windows
**C drive**. Sixteen block hashes, the full stored-file readback hash and the
peer acknowledgement matched. The worker reported 0.73709 seconds through
transfer/flush and 0.18558 seconds for full readback. This includes protocol,
hashing and file operations; it is not a pure-network speed test. The stored
payload, generated worker, compiler scratch and narrow temporary firewall rule
were removed after success. Evidence and the content-generation recipe remain.

A subsequent raw TCP upload-then-download check transferred 64 MiB in each
direction with matching SHA256. Each business connection was attempted once.
Receiver payload timers measured approximately 203 MB/s Mac → Windows and
395 MB/s Windows → Mac. The sender's socket-enqueue timer was not treated as
received throughput. These are short laboratory samples with concurrent work
left running, not a maximum-rate measurement or a sustained-traffic pass.

The first preparation of this TCP check stopped before starting a listener or
creating a firewall rule: an old install-result file still recorded the earlier
failed binding attempt. Its historical evidence was preserved. A separate new
run checked the live exact device, PnP/service/INF and current service-file hash
instead of accepting or rewriting that stale record.

## Immediate-enable control: another failed 600-second acceptance

One disable (exit 0) followed immediately by one enable (exit 0) reproduced the
failure. No intentional hold was inserted; the recorded hold was 0.000154 seconds.
The parent and network adapter remained absent in all recovery observations,
including the last one at 599.837 seconds after enable. The 600-second window
expired without recovery. There was no extra reset, scan or reinstall.

```text
3.596621 USBNCM: D0Exit to state 5
3.882163 USBNCM: Idle power management disabled
3.883135 USBNCM: WdfUsbTargetDeviceCreateWithParameters FAILED 0xC000000E
3.883141 USBNCM: InitializeDevice failed 0xC000000E
```

ETW reported 30537 events, zero lost and one metadata schema warning. Target
port 17 again changed `0x203 → 0x2C0 → 0x2A0`, with the same two event-123
failures seen in the short-recovery restart trial. Its own Windows clock placed
these at 16:59:08.126 and 16:59:08.230. The trace had no subsequent successful
target enumeration within the capture.

This time the live Mac stream did capture On → Suspended → On, USB reset and
On → Off. Its local reset-to-Off interval was about 5.4 ms. That interval is
within one Mac clock; it does not align Windows driver callbacks to the Mac.

### Additional confound: lock state

The Mac was demonstrably unlocked during earlier client interaction before the
30-second-hold trial, but locked before the immediate-enable control. Its lock
state and the hold duration were not controlled independently. Thus the tests
cannot yet distinguish a timing effect, a lock/accessory-security effect or
ordinary variability. No security or sleep policy was changed.

A compact registry snapshot while locked showed the device-role USB-C port's
USB2/USB3 transports as `Policy Authorized`, with no pending authorization;
the USB device controller was in power state 0 and the main NCM had
`HostAttached=0`. Another host-role port reported pending/unauthorized transports;
that must not be confused with the direct NCM device-role connection. These
records do not prove that authorization caused the direct-link shutdown.
[Apple's accessory-access documentation](https://support.apple.com/en-gb/102282)
confirms that lock state can matter for accessory approval in general, not that
it explains this device-mode failure.

Final read-only Windows inspection found the parent registered but not Present,
no corresponding adapter/address, driver service Stopped, configuration flags 0
(not left administratively disabled), and the expected service-file hash on
disk. This is not proof that the SYS remains loaded. Independent management
was Preferred, with zero Windows default routes. Captures were stopped; their
completed one-shot tasks and empty compiler scratch directories were removed.
All failure evidence was retained. The USB link remained unavailable at this
inspection; the next minimal check is unlock-only observation without a cable
operation before more destructive tests.

## Questions for cloud review

Please analyze the exact frozen PR #1 source alongside these observations and
label conclusions as observation, inference or untested hypothesis.

1. Which lifecycle paths could leave the USB parent absent during framework
   target creation, then allow delayed re-enumeration? Distinguish Windows
   hub/UCX/PnP behavior, driver lifecycle and Mac device-mode behavior.
2. What minimum additional USB hub/UCX/PnP tracing and source-level diagnostics
   would distinguish these possibilities without repeated blind resets?
3. Propose a bounded next hardware test, with independent management, local
   monotonic timing, explicit expected events and stop/rollback criteria.
4. Are any source changes justified by the evidence now? If not, specify what
   evidence is missing. Do not substitute unconditional retries, swallowed
   `STATUS_NO_SUCH_DEVICE`, NTB/MTU tuning or passing mocks for enumeration proof.
5. How do the second trial's port-status changes, successful control requests
   and new-object enumeration change the hypothesis ranking? Verify numeric
   interpretations from primary definitions; distinguish a USB3 link/resume
   interaction from NCM interface teardown, without assigning blame from
   temporally adjacent events alone.

Cloud Linux analysis cannot validate Windows kernel loading, actual USB
re-enumeration or hardware stability. Do not merge or release binaries based on
this report. Keep delayed recovery distinct from successful bounded recovery.
