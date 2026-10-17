# Security

Do not post credentials, cookies, tokens, encryption keys or source containing secrets in public issues. For a self-hosted installation, report suspected vulnerabilities privately to its operator using the operator's published support channel. No public service or dedicated reporting mailbox is operated by this repository yet.

If a session may be compromised, disconnect ACMP locally, revoke access at the identity provider, remove the plugin from ChatGPT, and use ACMP's own account/session controls where available. Rotate encryption keys through a controlled migration or reconnect all accounts. Review whether backups or infrastructure logs contain affected data.

Deploy one process/replica with a persistent volume, HTTPS and a configured established OAuth issuer. Never disable authentication for a public endpoint. See [authentication](docs/AUTH.md), [deployment](docs/RAILWAY.md) and [privacy](docs/PRIVACY.md).
