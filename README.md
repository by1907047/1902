# Apple 1902 USB NCM for Windows

[简体中文](README.zh-CN.md) · [Build](docs/BUILDING.md) · [Test results](docs/TESTING.md) · [Known issues](docs/KNOWN_ISSUES.md)

An experimental Windows x64 USB network driver for the Apple `05AC:1902` composite device exposed by a Mac over a USB data cable. It builds a custom KMDF/NetAdapterCx `.sys`; this is **not** an INF wrapper around Windows' built-in `UsbNcm.sys`.

**Alpha, laboratory use only.** `v0.1.0-alpha.2` provides a neutral-path, test-signed x64 package with revision-specific short hardware checks. The maintainer attributes the earlier USB3 fault to the old cable and locked reconnect to Mac accessory approval; this is not a qualification of every transport or power transition. There is no Microsoft signature, WHQL certification, or production support. Keep an independent management connection.

## Scope

| Item | Current boundary |
| --- | --- |
| Windows | x64; INF requires Windows build 26100 or newer; hardware tests used build 26200 |
| USB device | Exactly `USB\VID_05AC&PID_1902`, composite parent; not an `MI_XX` child |
| Mac | One M1 MacBook Pro tested; other models and macOS versions need verification |
| Cables | One USB2 High-Speed and one USB3 SuperSpeed setup tested; charging-only cables cannot work |
| Signing | Test-signed laboratory package; normal Secure Boot policy has not been validated |
| Non-goals | Thunderbolt networking, iPhone tethering, general Apple-device support, automatic internet sharing |

The cable, port, Mac USB device mode, driver, and IP configuration all have to work. The driver does not create Mac device mode, repair a charging-only cable, or automatically configure routing, SMB, firewall rules, or sleep settings. A USB cable's advertised rate is not the achieved network throughput.

## Get started

Clone this repository; the DMF dependency is vendored, so no submodule initialization is required. Run the portable checks on macOS or Linux with Python 3 and Clang:

```sh
python3 tools/run_portable_tests.py
```

For a Windows build, follow [BUILDING](docs/BUILDING.md). Before any laboratory installation, read [INSTALLING](docs/INSTALLING.md) and [SIGNING](docs/SIGNING.md). The source INF contains build-time placeholders and is **not** an installable driver package.

The alpha.2 release asset contains SYS/INF/CAT and a **public test certificate**, not its private key. It is not for normal Secure Boot systems; no security-policy-changing installer is supplied. The personal-path historical package remains withheld. See [alpha.2 validation and boundaries](docs/2026-10-10-alpha2-validation.md), [installation](docs/INSTALLING.md) and [signing](docs/SIGNING.md).

Function-level idle suspend remains disabled: the tested Mac configuration does not declare the remote-wake capability needed to preserve inbound access. USB link low-power behavior remains under Windows/hardware control. See the [power-management plan](docs/POWER_MANAGEMENT.zh-CN.md).

## Project layout

```text
NCM-Driver-for-Windows/   driver source, projects, vendored DMF and upstream notices
tests/                   portable source-contract and extracted-function probes
tools/                   portable test runner and snapshot verifier
docs/                    build, safety, results, limitations and provenance
.github/                 portable CI and issue templates
```

Release `v0.1.0-alpha.1` is a frozen export of the hardware-tested reconnect candidate. Later changes in the [CHANGELOG](CHANGELOG.md) have revision-specific native and hardware results in [OUT-PIPE-RECOVERY](docs/OUT-PIPE-RECOVERY.md); results do not carry forward automatically. See the [integration lessons](docs/2026-10-10-lessons-and-source-integration.zh-CN.md). [PROVENANCE](docs/PROVENANCE.md) records source identities. CI uses operating-system shims; it cannot establish kernel or hardware safety.

## Contribute

Useful contributions include reproducible USB3 stall reports, lifecycle fixes, accurate link-rate reporting, and tests on other cable/port/OS combinations. See [CONTRIBUTING](CONTRIBUTING.md). Please redact serial numbers, account names, addresses and credentials from reports.

Derived from [shrekoverflow/apple-ncm](https://github.com/shrekoverflow/apple-ncm) and the [Microsoft NCM sample](https://github.com/microsoft/NCM-Driver-for-Windows), with Microsoft DMF vendored. The published Windows subtree retains its MIT license; Linux code from the upstream repository is not included. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md). This is not an Apple or Microsoft official driver.
