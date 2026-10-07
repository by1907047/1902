# Security

This alpha kernel driver is not production-qualified. Bugs may crash a machine or lose connectivity; malformed USB input and lifecycle races are security-relevant. Test only with an independent recovery path.

Do not include private keys, credentials, BitLocker recovery keys, full crash dumps or raw packet/device traces in public issues. For ordinary bugs, open a redacted issue using the template. For a vulnerability, use GitHub's **Report a vulnerability** option if available; otherwise open only a minimal request for a private reporting channel, without exploit details or sensitive attachments.

No security response time or supported production release is promised. Reports should identify the public source commit, affected function and minimal synthetic reproducer where possible. An inherited Microsoft sample security document does not mean Microsoft maintains this derivative.
