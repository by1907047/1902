# Changelog

## Unreleased

Source changes after the frozen candidate. **Not built with the WDK and not hardware-tested**; the 0.1.0-alpha.1 hardware results do not apply to them.

- Report link speed from USBD connection capabilities (SuperSpeed 5 Gb/s, High-Speed 480 Mb/s, Full-Speed 12 Mb/s, unknown on query failure) instead of KMDF's `AT_HIGH_SPEED` trait, which is also set at SuperSpeed. The speed is now recorded before the first link-up indication.
- Reject device OUT NTB parameters whose `dwNtbOutMaxSize` cannot hold one maximum-size datagram under the advertised divisor/remainder/alignment; previously TX silently dropped every such frame.
- Release the configuration-descriptor and friendly-name buffers on every path instead of leaving them parented to the WDFDEVICE across repeated PrepareHardware.
- Remove unreachable interrupt-pipe, placeholder-instance and raw-URB code; the removed CDC notification handler read a 16-byte speed-change notification after checking only 8 bytes.
- Negotiate a device-advertised `dwNtbInMaxSize` above the host limit (64 KiB for NTB32, 65535 for NTB16) down with `SET_NTB_INPUT_SIZE` instead of rejecting the device.
- Cap the receive backlog at 128 queued NTBs (about 8 MiB) instead of growing non-paged memory without bound; further NTBs are dropped and counted. A dropped or undeliverable continuous-request-target buffer (function driver) is now returned to its owner instead of leaking.
- Diagnostics only, no recovery change: count and log (1st, 2nd, 4th... occurrence) TX send failures, TX completion failures with USBD status, TX cancellations, RX continuous-reader failures and RX backlog drops. Log prefixes are `Sideline1902: TX`, `Sideline1902: RX readers failed` and `USBNCM: RX NTB dropped`. The RX readers-failed callback returns TRUE, which keeps KMDF's default pipe reset and restart.
- Correct the TX diagnostics labels: KMDF reports a request cancelled by its own 5 s send timeout as `STATUS_IO_TIMEOUT`, so timeouts are now counted and logged as `TX timed out` instead of falling into `TX completion failed`; `TX cancelled` now means `STATUS_CANCELLED` only.
- Experimental, off by default: bulk-OUT instrumentation and a pipe-only data-path recovery, selected by the `Sideline1902DataPathDebug` device value (0 off, 1 instrumentation, 2 recovery, 3 both). Off creates no lock or work item and does no admission or in-flight bookkeeping; the remaining off-state differences are listed in `docs/OUT-PIPE-RECOVERY.md`. Recovery serializes every stop, reset and start of both data pipes under one wait lock; in recovery mode the IN readers-failed callback returns FALSE and the driver performs the IN pipe reset itself under that lock, so the framework never resets the pipe or the port outside it. OUT recovery after `USBD_STATUS_XACT_ERROR` closes a send-admission gate, drains active sends, cancels sent I/O, resets the pipe with a 2 s request timeout and reopens only after a successful start; at most 3 attempts per D0 session, 10 s apart; never a port or device reset. A restart is logged as "pipe restarted, data recovery unverified", with separate markers for the first send offered and the first success after it. `out_recovery_probe.py` runs the production code against a KMDF model, including the framework's reader recovery, with threads, and compares switch 0 with the frozen `2327f448cf6c` data-path code.
- Add `ntb_fit_probe.py` (validation vs. the real TX NTB template), `host_memory_probe.py` (per-call failure injection for WDFMEMORY lifetime), `host_diagnostics_probe.py` (counters, bounded logging and unchanged TX/RX behavior), RX backlog-cap and buffer-ownership checks, and link-speed/NTB-fit checks in `validation_tests.cpp`. `docs/source-snapshot.json` stays the immutable `v0.1.0-alpha.1` baseline; post-baseline changes are recorded separately in `docs/source-current.json`.
- `check_snapshot.py` now verifies the baseline manifest against a pinned hash and against tag `v0.1.0-alpha.1` (CI fetches full history for this), and separately verifies that every tracked file in scope is either byte-preserved or listed as changed/added/removed. `source_identity_tests.py` covers the rejection cases.

## 0.1.0-alpha.1 — 2026-10-07

First public **source-only** snapshot of the frozen `d522ef2-dirty-469555eaf6648073` reconnect candidate. This is a packaging/documentation release, not a newly validated driver fix.

- Publish the Windows driver and exact vendored DMF snapshot with upstream MIT notices.
- Include portable INF, parser, NTB, buffer, queue, adapter lifecycle and host reprepare tests.
- Add English/Chinese README, build/safety/rollback documentation, sanitized historical results, provenance and portable CI.
- Exclude Linux code, machine-specific helpers/logs, secrets and historical binaries.

Open limitations include USB3 stalls/recovery, long-duration testing, link-rate metadata, upload asymmetry and Microsoft signing. No Windows build, driver installation, security-policy change or hardware test was performed for this publication.
