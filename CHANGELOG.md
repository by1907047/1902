# Changelog

## Unreleased

Source changes after the frozen candidate. **Not built with the WDK and not hardware-tested**; the 0.1.0-alpha.1 hardware results do not apply to them.

- Report link speed from USBD connection capabilities (SuperSpeed 5 Gb/s, High-Speed 480 Mb/s, Full-Speed 12 Mb/s, unknown on query failure) instead of KMDF's `AT_HIGH_SPEED` trait, which is also set at SuperSpeed. The speed is now recorded before the first link-up indication.
- Reject device OUT NTB parameters whose `dwNtbOutMaxSize` cannot hold one maximum-size datagram under the advertised divisor/remainder/alignment; previously TX silently dropped every such frame.
- Release the configuration-descriptor and friendly-name buffers on every path instead of leaving them parented to the WDFDEVICE across repeated PrepareHardware.
- Remove unreachable interrupt-pipe, placeholder-instance and raw-URB code; the removed CDC notification handler read a 16-byte speed-change notification after checking only 8 bytes.
- Add `ntb_fit_probe.py` (validation vs. the real TX NTB template), `host_memory_probe.py` (per-call failure injection for WDFMEMORY lifetime) and link-speed/NTB-fit checks in `validation_tests.cpp`. Snapshot entries for the changed pinned files are updated.

## 0.1.0-alpha.1 — 2026-10-07

First public **source-only** snapshot of the frozen `d522ef2-dirty-469555eaf6648073` reconnect candidate. This is a packaging/documentation release, not a newly validated driver fix.

- Publish the Windows driver and exact vendored DMF snapshot with upstream MIT notices.
- Include portable INF, parser, NTB, buffer, queue, adapter lifecycle and host reprepare tests.
- Add English/Chinese README, build/safety/rollback documentation, sanitized historical results, provenance and portable CI.
- Exclude Linux code, machine-specific helpers/logs, secrets and historical binaries.

Open limitations include USB3 stalls/recovery, long-duration testing, link-rate metadata, upload asymmetry and Microsoft signing. No Windows build, driver installation, security-policy change or hardware test was performed for this publication.
