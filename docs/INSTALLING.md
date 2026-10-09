# Laboratory installation and rollback

Alpha.2 includes a test-signed laboratory package, not a Microsoft-signed production driver. These notes are not a one-click installer or a recommendation to weaken a daily-use computer's security settings. Check [the exact validation record](2026-10-10-alpha2-validation.md) first.

## Before installation

Use a recoverable test machine. Keep an independent Ethernet management link and local access. Stop at an agreed maintenance window if computation or other important work is running. Save any BitLocker recovery material privately before considering firmware or boot-policy changes; never post it to an issue.

In Device Manager, inspect the hardware IDs of the **composite parent**. It must include exactly `USB\VID_05AC&PID_1902`. Do not force the driver onto an interface child, another Apple product or another network adapter. Record the current driver's published OEM name and export that exact package with `pnputil /export-driver <recorded-oem-name> <backup-directory>` if one is present. Do not copy an OEM number from someone else's machine.

Hash the generated files and verify the SYS signature and catalog membership with the WDK's SignTool. A matching hash proves file identity, not trust or compatibility. Compare the source and package identity against the build record. Establish an explicit signing/trust plan first; see [SIGNING](SIGNING.md).

## Install only an eligible, verified package

For an administrator on the intended laboratory machine, the normal package-install command is:

```powershell
pnputil /add-driver "C:\build\apple1902\package\SidelineAppleNcm1902.inf" /install
```

The path is an example; use your verified extracted package path. Successful staging does not prove the device has bound or the kernel has loaded the driver. Check the selected driver, running service, device problem code and Code Integrity events. Reject a wrong-device binding or a trust failure; a consent dialog cannot override kernel Code Integrity.

For alpha.2, verify every file against `SHA256SUMS`, and verify SYS/CAT signer identity and catalog membership. Use an authorized test machine with an established test-signing policy and an explicit trust plan; importing `Test.cer` changes machine trust and is not an automatic installation step. Do not disable Secure Boot, HVCI or other protections merely to try this release. No private key is needed for installation. The test certificate is short-lived and the package has no timestamp.

IP addresses and MTU must be configured on both ends deliberately. Do not add a default route or enable internet sharing just to test this link. Start with mutually supported settings; the historical MTU 8000 tests do not establish a universal default. When testing throughput, verify that payloads actually use USB rather than an Ethernet SMB multichannel fallback.

## Rollback

First preserve a small, redacted failure report and restore access over the independent link. In Device Manager, use Roll Back Driver where available, or remove **only the newly recorded package** and install the previously exported, verified package. An administrator can remove a confirmed package with:

```powershell
pnputil /delete-driver <newly-recorded-oem-name> /uninstall
```

The angle-bracket names are placeholders to replace, not literal commands. Do not use wildcard OEM deletion, `/force`, or reboot while important work is running. Follow Windows' reboot requirement if prompted during a maintenance window. Restore only the IP/MTU/firewall settings you changed and separately restore any authorized boot-policy changes. Package removal alone does not reset them.

No script in this public project changes Secure Boot, TESTSIGNING, certificate stores, EFI keys, sleep configuration or production network settings.
