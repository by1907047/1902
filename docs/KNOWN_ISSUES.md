# Known issues and roadmap

Current experimental status is in [OUT pipe recovery](OUT-PIPE-RECOVERY.md).
Older observations below are labeled historical; they are not results
for every later source revision. The PR remains draft/unmerged and
source-only. Finite business passes do not establish fault-free
transport or long-term qualification.

## Open issues

1. **Initiating USB3 OUT transaction error remains unexplained.** Historical reconnect tests stalled both directions after upload/download, and a successful PnP call did not ensure an immediately usable adapter. Later native captures identify a real OUT transaction error followed by canceled send-timeout tails. Experimental pipe-only recovery now exists; `81fb3e6` has one native-plus-SHA supported recovery and `59d64b7` has two finite 600 s business passes, with five narrow native-plus-SHA recovery chains in T1. T2 has no observed payload OUT XACT, but both traces retain startup pairing exceptions and global analysis-quality failure. This does not fix the initiating error or establish unconditional reconnect. See [revision-specific status](OUT-PIPE-RECOVERY.md).
2. **Long-duration qualification remains incomplete.** The two 600 s originals belong to `59d64b7`; newer RX revision `38709d3` passed its own 600 s original, with one narrowly supported native old-request-drain/reset/new-OUT/SHA recovery chain, and a separate default-mode0 C-file smoke. Its global analysis-quality gap remains. Natural credit Deferred wait and exhaustive ordinary queue-stop continuity are not natively covered. Overnight transfers, repeated hot-plug, genuine sleep/wake, port changes, memory/leak checks and power transitions remain open. See [revision-specific limits](OUT-PIPE-RECOVERY.md).
3. **Conservative SuperSpeedPlus link reporting.** Historically Windows advertised 480 Mb/s even on SuperSpeed because the code used KMDF AT_HIGH_SPEED. The Windows USBD-capability correction has now been natively built and tested: the observed SuperSpeed connection advertises 5 Gb/s. The Mac interface still shows a conservative 100 Mb/s label; that separate interface label is not the USB bus rate or measured payload throughput. SuperSpeedPlus is still conservatively reported as 5 Gb/s rather than an exact higher negotiated rate. A link-rate label is not measured payload throughput; cable/device maximum capability is not the negotiated bus rate.
4. **Upload/download asymmetry.** USB3 memory upload was slower than download in short measurements. No function-level cause or validated optimization has been established. File-upload measurements also include hashing, disk writes, flushing and acknowledgements.
5. **SMB can use the wrong path.** A USB-addressed share may still use an Ethernet multichannel fallback. Existing SMB observations cannot be presented as USB throughput. This repository does not disable SMB security or global multichannel behavior.
6. **Limited compatibility and trust coverage.** Only one Mac/workstation setup was tested. No Microsoft signature, WHQL/HLK qualification or normal Secure Boot + TESTSIGNING-off load result exists. Source INF architecture/build restrictions must not be broadened without testing.
7. **Build warnings, signing and binary publication.** Native build summaries for `9d3f3cb`, `59d64b7` and `38709d3` all retain 70 Debug / 68 Release warnings; strict, consistently normalized comparisons found no new warnings. Earlier 53/51 summaries used a different counting method and are not evidence of a reduction. Neutral-path native rebuilds and private test-signed installations now exist, but are not warning-free builds or certification. No binary is publicly released; exact package verification, applicable qualification and an authorized Microsoft-signing route remain separate release gates.

## Next milestones

- Qualify each exact new neutral-path package separately; preserve source/SYS identity, warnings, failed runs and private signing boundaries.
- Reproduce upload-then-download failure with exact source/SYS identity, bounded diagnostics, timeouts and reliable cleanup.
- Fix lifecycle/data-path behavior based on that evidence; test software restart, physical reconnection and USB2 ↔ USB3 transitions separately.
- Validate sustained bidirectional traffic, true sleep/resume and memory behavior on dedicated hardware.
- Improve exact SuperSpeedPlus rate/unknown handling without presenting a bus-class label as payload throughput.
- Evaluate authorized Microsoft signing and applicable HLK testing; release a binary only with an accurate trust label.

Passing portable CI is not acceptance of these milestones. A future fix must include a regression test and separate real-hardware evidence where the operating system or USB bus is involved.
