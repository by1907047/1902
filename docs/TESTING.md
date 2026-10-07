# Testing and historical results

This is a sanitized summary of archived **2026-10-02** laboratory records. It is not a new hardware test for the 2026-10-07 publication. Private logs, serial numbers, interface GUIDs, remote-management addresses and trace captures are deliberately excluded.

## Candidate identity

The exported source is the reconnect candidate `d522ef2-dirty-469555eaf6648073`, based on internal commit `d522ef239f613747155dc4a30db55447e6de5e59`. It includes the frozen host changes rather than pretending the base commit alone identifies the tested build. [PROVENANCE](PROVENANCE.md) records hashes and exclusions.

Hardware records used a MacBook Pro M1 and Windows 11 x64 build 26200 on a Dell Precision 7920. The archived test-signed driver ran with HVCI enabled and Secure Boot disabled. That is not validation under normal Secure Boot policy. Published code is not a guarantee for another host or cable.

## Observed results

| Test | Archived result | Boundary |
| --- | --- | --- |
| Native build | Debug/Release zero errors; 70/68 warnings; independent incremental gate exit 0; InfVerif passed | Not a new build, certification or warning-free result |
| Software PnP restart | Three successful restart/configuration cycles; short bidirectional checksum tests passed | Later failure disproves unconditional recovery |
| USB2 memory TCP | Three upload/download pairs of 64 MiB; median upload 47.44 MB/s, download 40.77 MB/s | HS 480 Mb/s, bulk packet size 512; not disk or SMB |
| USB2 C-drive file upload | 128 MiB; 35.29 MB/s; block hashes, flush and readback verified | Includes protocol, hashing, disk I/O, acknowledgements and logging |
| USB3 C-drive file upload | 128 MiB; 92.91 MB/s; hashes, flush and readback verified | Observed SS 5 Gb/s class, bulk packet size 1024; not pure network speed |
| USB3 return sequence | Upload succeeded, next download timed out; both directions stalled | Six-transfer sequence failed, not an overall pass |
| Failure recovery | PnP call returned 0, no adapter within 45.60 s; later reappeared | Cause and recovery timing unknown |
| Closed-lid follow-up | 1 MiB and 64 MiB downloads passed; latter 395.46 MB/s | Mac sleep was disabled; not genuine sleep/resume validation |

USB2 and USB3 observations did not establish a strictly unchanged physical port pairing. Do not infer a controlled cable-only comparison. MB/s above is decimal bytes per second, while payload sizes use MiB.

The older `d522ef2` binary completed a 600-second, 51.22 GiB alternating-transfer experiment. **That result does not belong to this reconnect candidate** and cannot qualify it for long-term use. Raw performance captures also had unresolved symbol-analysis limitations; no claimed function bottleneck is published.

## Portable tests

Run `python3 tools/run_portable_tests.py` with Python 3 and Clang. The runner checks the published snapshot and executes INF binding checks, build-policy contracts, USB descriptor validation, NTB boundaries/chains, OUT-NTB fit against the real TX template, link-speed classification, RX completion/rings/stop behavior, TX advance, buffer failures, adapter lifecycle, repeated-prepare control flow and per-prepare WDFMEMORY release.

The C++ probes extract selected real source functions but replace WDF/DMF/NetAdapterCx interfaces with shims. They use AddressSanitizer and UndefinedBehaviorSanitizer for those fixtures. They do not reproduce OS scheduling, USB hardware, all allocation paths or kernel signing enforcement. A pass is a local regression signal, not proof the SYS is safe.

For future hardware results, record the repository commit, SYS hash, OS/kit, negotiated USB rate, cable/ports, MTU, payload size, direction, timing scope and checksum outcome. Keep failures and partial byte counts. Do not silently retry or reset the device during a timed run. Use the Windows **C drive**, not D, for new disk-target measurements and delete only test-owned payloads after retaining the results. Keep an independent control link.
