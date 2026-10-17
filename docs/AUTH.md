# Authentication and account linking

Concrete first private deployment: [Auth0 + Railway walkthrough (Russian)](PRIVATE_SETUP.ru.md).

## Two separate identities

The MCP server is an OAuth resource server. Use an established OAuth/OIDC provider (for example an operator-managed Auth0 tenant), rather than a new password database or a handwritten authorization server. The provider authenticates each plugin user. A separate HTTPS page `/connect` links that identity to acmp.ru using the site's actual login form. ACMP has no verified official OAuth API.

Never request an ACMP password in ChatGPT. The linking form transmits the password to this server and then to `https://acmp.ru/index.asp?main=enter`; it is not persisted. Cookies are encrypted using `SESSION_ENCRYPTION_KEY` before storage. Cookie values, browser-session tickets, bearer tokens and passwords are never returned by tools.

## Required provider contract

1. Create an API/resource identifier **exactly** `https://YOUR_HOST/mcp`. Tokens must have this value in `aud`, the configured issuer in `iss`, a stable nonempty `sub`, `iat`, and `exp`. Access tokens must be signed with RS256 and advertise `acmp:read`, `acmp:submit`, `acmp:manage` in their space-separated `scope` claim. Do not use opaque access tokens or ID tokens as MCP bearer tokens.
2. Publish authorization server metadata at the issuer's standard well-known endpoint. Include authorization/token endpoints, `code_challenge_methods_supported: ["S256"]`, and supported client authentication methods. Implement authorization code + PKCE, resource/audience binding and user consent at the provider. Configure refresh tokens and their rotation there, if needed.
3. Register a dedicated OAuth client for ChatGPT, using the exact redirect URI shown by ChatGPT's plugin setup. A predefined client ID/secret is supported; this project does not implement DCR or CIMD itself. The provider may support either. Never allow wildcard or caller-provided redirect URIs.
4. Ensure the provider accepts MCP's `resource=https://YOUR_HOST/mcp` and mints that audience. Some providers normally require `audience` instead: configure their MCP/resource-indicator support or an established gateway. Merely creating an API in a provider does not prove the `resource` contract works. Verify this with the provider and MCP Inspector before launch.
5. Create a **separate OIDC web application** for the connection portal with callback exactly `https://YOUR_HOST/connect/callback`. Enable authorization code, S256 PKCE and ID tokens with `openid` scope. Use client-secret POST if a confidential portal client is configured. Set `PORTAL_CLIENT_ID`, `PORTAL_CLIENT_SECRET`, `OIDC_AUTHORIZATION_ENDPOINT`, `OIDC_TOKEN_ENDPOINT` accordingly. No ACMP credentials belong in these variables.
6. Ensure the same human has exactly the **same `iss` and `sub`** in the ChatGPT API access token and portal ID token. Pairwise subjects per OAuth client are incompatible without a provider-side stable mapping. Never map users by email, display name, or a model-supplied identifier.

Copy the exact issuer, including its trailing slash, into `OAUTH_ISSUER`; put its JWKS URL in `OAUTH_JWKS_URL`. Generate a Fernet encryption key privately and keep it across restarts:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

The server verifies signatures, algorithm allowlist, issuer, audience, expiry and required claims on every bearer request. The SDK enforces `acmp:read` on `/mcp`; handlers additionally enforce submit/manage scopes. Protected-resource discovery is served at both `/.well-known/oauth-protected-resource/mcp` and `/.well-known/oauth-protected-resource`. The 401 challenge advertises the metadata URL.

Provider refresh, consent, client registration and revocation are provider responsibilities. The server does not pass ChatGPT bearer tokens to ACMP. JWT revocation is bounded by token expiry; use short-lived access tokens (for example 5–15 minutes), revoke refresh tokens at the provider, and unlink the plugin in ChatGPT when needed.

## User workflow

1. Connect the MCP plugin to ChatGPT using OAuth and consent to the desired scopes.
2. Ask for `get_account_status` and open its connection URL.
3. Sign into the portal using the same provider identity.
4. Enter ACMP credentials on that page. Login is checked against the real ACMP task page. An account can be linked to only one provider identity at a time.
5. Return to ChatGPT and check account status. On expiry, repeat the connection step.
6. Use the page's Disconnect or Delete all my stored data buttons, or explicitly ask ChatGPT to call `disconnect_account`. Local deletion does not remove ACMP submissions or the identity-provider account.

Browser login state is random, encrypted, expiring, single-use and bound to an HttpOnly cookie; ID-token nonce and issuer are checked. The account forms require an expiring server session, exact Origin and CSRF token. Login credentials never appear in URLs. Sign-in and linking are rate limited. CSP disallows scripts, embedding and third-party resources. Built-in application access logs are disabled to avoid logging OIDC codes.

## CAPTCHA and session problems

The client distinguishes a remaining login form (rejected credentials or expiry), a CAPTCHA form, and an unexpected page format. It does not solve or bypass CAPTCHA. If ACMP requires interactive verification on the hosting IP, automated linking cannot complete; the user must complete the site's supported verification and try later. Browser cookies are not collected through chat, and no extension/cookie-import bypass is implemented.

## Login bug fixed

Live investigation on 2026-10-16 confirmed that the site accepted the supplied test account and set session cookies. The old parser searched for the numeric identity only before the first sidebar `menu_title`. The actual `Мои задачи` account link is in the sidebar, while the header contains only a display name and Logout. The parser now uses that labeled account link together with independent header logout evidence and rejects login forms or conflicting identity signals.

## Deployment acceptance checklist

The complete browser flow and cryptographic token checks are tested against a local mock OIDC provider, not a configured external tenant. Before public service, verify real provider discovery, resource binding, callback allowlist, consent, refresh, stable cross-client subject mapping and logout/revocation. No real ChatGPT OAuth connection has been claimed.

Official guidance: [OpenAI authentication](https://developers.openai.com/apps-sdk/build/auth) and [MCP authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
