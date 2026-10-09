# Apple1902 v0.1.0-alpha.2 package

Experimental x64 laboratory package, **test-signed only**. Not Microsoft-signed,
not WHQL-certified, not suitable for normal Secure Boot policy. Do not depend
on it as your sole management connection.

Build source: `5ed5a1a4d6715b48d6b87a28e937129b17e71452`.
Integrated main `4a5b1bb46a875248d16ffb83f683bf0c3d290a8d` has identical
driver/test/tool source. Documentation-only release commits may follow.
Build: offline EWDK 26100 x64 Release, neutral `C:\build\apple1902` paths.
Generated INF DriverVer: `10/10/2026,1.30.40.58`.

The zip contains the SYS, generated INF, signed CAT, public `Test.cer`, licenses,
installation/signing/validation documentation and a SHA256 manifest.
No PFX, private key, personal-path old binary, installer or security-policy
helper is included. Verify **all files** using `SHA256SUMS`, then independently
verify signature and catalog membership before use.

Public test certificate thumbprint: `02CD531C083B5ED30DBC437E31D460D2B0DA90F0`.
Expires **2026-11-08 18:11:40 UTC**; the package has no timestamp. Plan a verified
replacement before expiry. The certificate is not an EV/Microsoft credential.

Only an already eligible, authorized test setup was validated. The package
does not turn on test signing or turn off Secure Boot/HVCI. Trust import needs
an explicit administrator decision, not an “install anyway” assumption.

The driver matches only the `USB\VID_05AC&PID_1902` composite parent on supported
Windows x64 builds (26100+). It does not match an interface child or other Apple
devices. Keep a verified rollback package and independent Ethernet connection.
Do not copy another machine's published OEM number.

Experimental recovery remains default-off (device registry value missing or 0).
Function-level S0 idle suspend remains disabled: the tested Mac configuration
does not declare suspended-state remote wake. USB link LPM is separate and
remains Windows/hardware-controlled. No global power plan, IP/MTU, route, SMB,
internet sharing or security changes are automated.

Exact-package checks: eight 64 MiB SHA256-verified transfers, 32 MiB C-file
write/flush/readback, and one PnP restart followed by two 16 MiB verified
transfers. These finite checks are not long-duration, USB2, lock/sleep/wake or
experimental terminal-failure qualification. See the included validation record.
