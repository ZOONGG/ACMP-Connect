# Privacy and service limitations

This independent self-hosted integration is not endorsed by ACMP or OpenAI. The operator is responsible for hosting authorization, third-party terms, a public privacy notice and support contact. MIT covers the code, not ACMP content or branding.

## Data

| Data | Processing and retention |
| --- | --- |
| ACMP password | Authenticated HTTPS connection form and one login exchange; never saved or returned through MCP |
| ACMP cookies | Fernet authenticated encryption in SQLite; used only with HTTPS acmp.ru until local/site expiry or disconnection |
| OAuth bearer token | Verified per request; not saved or forwarded to ACMP |
| OIDC state and browser sessions | Random expiring tickets, hashed lookup keys and encrypted payloads; HttpOnly, SameSite Lax, Secure production cookies |
| Identity | Hash of issuer and subject, linked numeric ACMP ID; never identified by display name/email |
| Solution source | Request memory and ACMP upload only; a fingerprint is retained for idempotency |
| Submission journal | Identity hash, operation key, input digest, numeric account/task IDs, timestamps and results until explicit deletion |
| Problem/topic data | Returned from ACMP to the requesting client; rights remain with their owners |

The application does not deliberately log credentials, cookies, authorization headers or source. Process memory, OS paging, infrastructure telemetry, identity-provider records, ChatGPT history and ACMP's own submissions have separate retention. Protect both the volume and encryption key.

Expired ACMP sessions cannot be used. Encrypted expired records remain until relinking or deletion; seven-day TTL is not automatic physical deletion. Expired temporary tickets are removed when new tickets are created. The connection page contains no trackers or third-party assets.

## Disconnect and deletion

Disconnect removes local ACMP cookies. Delete also removes the user's operation journal and portal sessions. An active upload must finish before deletion to avoid racing an external mutation. ACMP submissions and identity-provider accounts are unaffected. SQLite free pages, WAL and operator backups can retain prior bytes until compacted or expired; operators must publish their backup retention policy.

Deleting the journal removes historical replay protection. After reconnecting, inspect ACMP before explicitly submitting old code again. Local cookie deletion does not remotely revoke an ACMP session; use site settings where supported. Revoke OAuth access at the provider and remove the plugin in ChatGPT separately.

## Isolation and availability

Identity comes exclusively from verified tokens. No tool accepts a user ID or cookies to impersonate another account. An ACMP account can be linked to only one provider identity at a time. Ownership is checked before compiler diagnostics are fetched.

Uploads require explicit user intent. There is no automatic solve/retry loop, CAPTCHA bypass, silent C-to-C++ fallback or invented verdict. ACMP statements and compiler logs are untrusted data.

HTML interaction is subject to site changes, CAPTCHA, limits and third-party authorization. There is no official ACMP API guarantee. Directory eligibility, desktop/mobile access and availability from a particular hosting network are not guaranteed.
