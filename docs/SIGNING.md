# Signing status

There is no Microsoft-signed or installable binary in this source-only release. The archived private package was self-signed for a controlled test setup. An ordinary certificate import or “install anyway” dialog does not establish kernel trust under normal Secure Boot policy.

The old test certificate expires on 2026-10-31 and the package was not timestamped. Neither that certificate nor its private key is distributed here. It is not an EV certificate or a Microsoft signing credential.

Microsoft's current guidance distinguishes HLK-tested dashboard signing, attestation for testing scenarios, and restricted preproduction signing. Attestation is not Windows certification and does not establish compatibility; preproduction signatures require explicitly provisioned test devices and are not trusted by default on retail systems. See [Driver signing options](https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/driver-signing-offerings).

For a production route, obtain an authorized hardware-developer identity, required certificate/submission access and applicable testing. Do not borrow private keys, impersonate Apple/Microsoft, or label an unverified third-party signature “WHQL”. A developer submitting on the project's behalf must identify the exact package, signing route and returned Microsoft artifact.

Acceptance requires the exact returned SYS/INF/CAT hashes and signature/catalog checks, then actual load and regression testing on the intended configuration: Secure Boot enabled, TESTSIGNING off, and the intended HVCI policy. This project has not completed that acceptance. It does not ship EFI-policy helpers, custom trust-chain bypasses or automated boot-security changes.
