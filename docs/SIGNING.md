# Signing status

There is no Microsoft-signed binary. Alpha.2 ships a self-signed laboratory package, separately built and tested in a controlled setup. An ordinary certificate import or “install anyway” dialog does not establish kernel trust under normal Secure Boot policy.

The historical private test certificate expires on 2026-10-31 and is not distributed. Alpha.2 uses a different, short-lived test certificate, expiring **2026-11-08 18:11:40 UTC**, without a timestamp. Only its public certificate is distributed; the signing key and temporary PFX were disposed of after signing. This is neither an EV certificate nor a Microsoft signing credential. The package is not a durable production deployment; plan a verified replacement before certificate expiry.

Alpha.2 was loaded with Secure Boot already off, test mode already on, and HVCI running. The release does not enable that policy or recommend changing a daily-use computer's security configuration. Exact identity and finite checks are in [alpha.2 validation](2026-10-10-alpha2-validation.md).

Microsoft's current guidance distinguishes HLK-tested dashboard signing, attestation for testing scenarios, and restricted preproduction signing. Attestation is not Windows certification and does not establish compatibility; preproduction signatures require explicitly provisioned test devices and are not trusted by default on retail systems. See [Driver signing options](https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/driver-signing-offerings).

For a production route, obtain an authorized hardware-developer identity, required certificate/submission access and applicable testing. Do not borrow private keys, impersonate Apple/Microsoft, or label an unverified third-party signature “WHQL”. A developer submitting on the project's behalf must identify the exact package, signing route and returned Microsoft artifact.

Acceptance requires the exact returned SYS/INF/CAT hashes and signature/catalog checks, then actual load and regression testing on the intended configuration: Secure Boot enabled, TESTSIGNING off, and the intended HVCI policy. This project has not completed that acceptance. It does not ship EFI-policy helpers, custom trust-chain bypasses or automated boot-security changes.
