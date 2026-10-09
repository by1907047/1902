# Known issues and roadmap

Current experimental status is in [OUT pipe recovery](OUT-PIPE-RECOVERY.md).
Older observations below are labeled historical; they are not results
for every later source revision. Recovery remains experimental, default-off
even in the alpha.2 test-signed package. Finite business passes do not establish fault-free
transport or long-term qualification.

## Open issues

**2026-10-10 status update:** the maintainer identifies the old cable as the
cause of the initiating USB3 fault, and Mac accessory approval as the cause
of locked reconnect. Current policy is Always Allow. Historical failures below
are retained, not retroactively marked passed. The alpha.2 exact package has
its own [finite default-mode0 validation](2026-10-10-alpha2-validation.md).
Experimental recovery modes 2/3 and their terminal-failure callbacks remain
unqualified on this exact package. Function idle suspend remains disabled:
the tested configuration reports no remote wake from a suspended state;
see [power-management plan](POWER_MANAGEMENT.zh-CN.md).

The [2026-10-10 integration note](2026-10-10-lessons-and-source-integration.zh-CN.md)
records a newer default-mode0 600 s pass after both cable and Mac port changed.
It does not isolate the old cable or qualify the current source on hardware.
Recovery-mode terminal pipe failures now indicate disconnected; both pipes
must successfully start before the indication is restored. This is readiness,
not a packet-delivery watchdog or automatic device restart.
Mode0/1 still ignores initial pipe-start status for compatibility with the
frozen data path; a framework-owned IN recovery failure in those modes is
also not surfaced as disconnected. Terminal reporting here is mode2/3 only.

1. **Initiating USB3 OUT transaction error remains unexplained.** Historical reconnect tests stalled both directions after upload/download, and a successful PnP call did not ensure an immediately usable adapter. Later native captures identify a real OUT transaction error followed by canceled send-timeout tails. Experimental pipe-only recovery now exists; `81fb3e6` has one native-plus-SHA supported recovery and `59d64b7` has two finite 600 s business passes, with five narrow native-plus-SHA recovery chains in T1. T2 has no observed payload OUT XACT, but both traces retain startup pairing exceptions and global analysis-quality failure. This does not fix the initiating error or establish unconditional reconnect. See [revision-specific status](OUT-PIPE-RECOVERY.md).
2. **Long-duration qualification remains incomplete.** The two 600 s originals belong to `59d64b7`; newer RX revision `38709d3` passed its own 600 s original, with one narrowly supported native old-request-drain/reset/new-OUT/SHA recovery chain, and a separate default-mode0 C-file smoke. Its global analysis-quality gap remains. Natural credit Deferred wait and exhaustive ordinary queue-stop continuity are not natively covered. Overnight transfers, repeated hot-plug, genuine sleep/wake, port changes, memory/leak checks and power transitions remain open. See [revision-specific limits](OUT-PIPE-RECOVERY.md).
3. **Conservative SuperSpeedPlus link reporting.** Historically Windows advertised 480 Mb/s even on SuperSpeed because the code used KMDF AT_HIGH_SPEED. The Windows USBD-capability correction has now been natively built and tested: the observed SuperSpeed connection advertises 5 Gb/s. The Mac interface still shows a conservative 100 Mb/s label; that separate interface label is not the USB bus rate or measured payload throughput. SuperSpeedPlus is still conservatively reported as 5 Gb/s rather than an exact higher negotiated rate. A link-rate label is not measured payload throughput; cable/device maximum capability is not the negotiated bus rate.
4. **Upload/download asymmetry.** USB3 memory upload was slower than download in short measurements. No function-level cause or validated optimization has been established. File-upload measurements also include hashing, disk writes, flushing and acknowledgements.
5. **SMB can use the wrong path.** A USB-addressed share may still use an Ethernet multichannel fallback. Existing SMB observations cannot be presented as USB throughput. This repository does not disable SMB security or global multichannel behavior.
6. **Limited compatibility and trust coverage.** Only one Mac/workstation setup was tested. No Microsoft signature, WHQL/HLK qualification or normal Secure Boot + TESTSIGNING-off load result exists. Source INF architecture/build restrictions must not be broadened without testing.
7. **Build warnings and production signing.** Native build summaries for `9d3f3cb`, `59d64b7` and `38709d3` retain 70 Debug / 68 Release warnings; normalized comparisons found no new warnings. Earlier 53/51 summaries used a different counting method and do not prove a reduction. Alpha.2 is a neutral-path test-signed package with finite default-mode0 checks, not a warning-free build or certification. Its short-lived certificate expires on 2026-11-08 without a timestamp. Microsoft signing, normal Secure Boot load, experimental terminal-failure qualification and broader compatibility remain separate gates.

## Next milestones

- Qualify each exact new neutral-path package separately; preserve source/SYS identity, warnings, failed runs and private signing boundaries.
- Reproduce upload-then-download failure with exact source/SYS identity, bounded diagnostics, timeouts and reliable cleanup.
- Fix lifecycle/data-path behavior based on that evidence; test software restart, physical reconnection and USB2 ↔ USB3 transitions separately.
- Validate sustained bidirectional traffic, true sleep/resume and memory behavior on dedicated hardware.
- Improve exact SuperSpeedPlus rate/unknown handling without presenting a bus-class label as payload throughput.
- Evaluate authorized Microsoft signing and applicable HLK testing; release a binary only with an accurate trust label.

Passing portable CI is not acceptance of these milestones. A future fix must include a regression test and separate real-hardware evidence where the operating system or USB bus is involved.
