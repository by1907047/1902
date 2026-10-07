# Known issues and roadmap

## Open issues

1. **USB3 download stall and uncertain recovery.** After returning from USB2 to USB3, an upload passed but the next download timed out and both directions stopped. One software PnP restart returned success, yet the adapter was absent for the following 45 seconds. It later recovered without a reported cable or lid change. This is not a fixed reconnect bug.
2. **No long-duration qualification of this candidate.** Earlier ten-minute results belong to an older binary, not this reconnect candidate. Overnight transfer, repeated hot-plug, genuine sleep/wake, port changes, memory/leak checks and power transitions remain to be tested.
3. **Incorrect advertised link rate.** Windows reported 480 Mb/s even on the observed SuperSpeed connection; the Mac-side interface also advertised a conservative rate. The released code used KMDF's `AT_HIGH_SPEED` trait, which is also set at SuperSpeed. An unreleased source change queries USBD connection capabilities instead; it is not built or hardware-tested, and SuperSpeedPlus links still report the 5 Gb/s Gen 1 rate. Cable labels, device maximum capability and payload throughput are not interchangeable with the negotiated USB rate.
4. **Upload/download asymmetry.** USB3 memory upload was slower than download in short measurements. No function-level cause or validated optimization has been established. File-upload measurements also include hashing, disk writes, flushing and acknowledgements.
5. **SMB can use the wrong path.** A USB-addressed share may still use an Ethernet multichannel fallback. Existing SMB observations cannot be presented as USB throughput. This repository does not disable SMB security or global multichannel behavior.
6. **Limited compatibility and trust coverage.** Only one Mac/workstation setup was tested. No Microsoft signature, WHQL/HLK qualification or normal Secure Boot + TESTSIGNING-off load result exists. Source INF architecture/build restrictions must not be broadened without testing.
7. **Build warnings and binary packaging.** Archived builds retain 70 Debug / 68 Release warnings. Old binaries contain personal build paths and are not published. A clean neutral-path rebuild will require fresh artifact verification and tests.

## Next milestones

- Build at a neutral C-drive path; collect diagnostics and verify artifacts without loading them automatically.
- Reproduce upload-then-download failure with exact source/SYS identity, bounded diagnostics, timeouts and reliable cleanup.
- Fix lifecycle/data-path behavior based on that evidence; test software restart, physical reconnection and USB2 ↔ USB3 transitions separately.
- Validate sustained bidirectional traffic, true sleep/resume and memory behavior on dedicated hardware.
- Correct link reporting using actual observed capabilities, with explicit handling of unknown rates.
- Evaluate authorized Microsoft signing and applicable HLK testing; release a binary only with an accurate trust label.

Passing portable CI is not acceptance of these milestones. A future fix must include a regression test and separate real-hardware evidence where the operating system or USB bus is involved.
