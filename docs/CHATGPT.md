# Connect to ChatGPT

For the first private connection, follow the [Auth0 + Railway walkthrough (Russian)](PRIVATE_SETUP.ru.md), including the read-only `get_problem` acceptance check. Copy the exact callback URI shown by ChatGPT; its format depends on provider issuer identification support.

The MCP implementation uses the official Python SDK and Streamable HTTP. A running local endpoint alone does not make it reachable by ChatGPT. Complete OAuth provider setup and deploy an HTTPS endpoint first; see [AUTH.md](AUTH.md) and [RAILWAY.md](RAILWAY.md).

According to the [official custom MCP server guide](https://developers.openai.com/api/docs/guides/custom-mcp-server#how-to-use), checked 2026-10-16:

1. Use ChatGPT on the web and open [Plugins](https://chatgpt.com/plugins).
2. Select the plus button, then **Add custom MCP server**.
3. Set the name to **ACMP Connect** and the server URL to `https://YOUR_HOST/mcp`.
4. Choose **OAuth**. Use the dedicated ChatGPT OAuth client configured at your provider, or the provider's supported DCR/CIMD flow. The server itself advertises an external authorization server.
5. Copy ChatGPT's exact callback URL into the provider's redirect allowlist. Request `acmp:read`, `acmp:submit`, and `acmp:manage` when all tools are needed. The provider must honor `resource` binding.
6. Review the permissions, create the plugin, install it, then sign in and consent.
7. In a conversation, mention `@ACMP Connect`. Check account status and open the secure linking page. Sign in there as the same identity and link ACMP.

Examples:

- “Use ACMP Connect to read problem 564 and solve it in C++. Do not submit yet.”
- “Submit this C++ solution to problem 1.”
- “Show my recent ACMP submissions.”
- “Check the verdict of submission ID … and explain the compiler error if available.”
- “Find problem A in the for-loop topic.”

Do not provide ACMP credentials in a conversation. Write tools are marked as mutations and may require ChatGPT confirmation. The tool description requires explicit intent before uploading; the server cannot independently inspect what the human wrote. Its durable idempotency checks remain enforced even if a client repeats an approved call.

## Desktop and mobile

The fetched official custom-MCP setup guide explicitly documents the web flow. Availability in ChatGPT Desktop, mobile, workspaces and locked-down accounts can differ. No desktop/mobile onboarding or tool-execution claim has been verified here. Use the web flow first, then test the installed plugin on each desired surface. A public-directory listing is separate from a personally configured custom MCP server.

## Troubleshooting

- **401 with discovery URL:** token missing/invalid, wrong issuer/audience/expiry, or missing read scope. Check the provider's resource binding and consent.
- **Write tool denied:** token lacks submit/manage scope. Update provider permissions and reconnect OAuth.
- **Account not connected:** open `/connect` and link the same provider identity. A separate identity creates a separate account context.
- **C compiler unavailable:** ACMP currently has no native C selection. Choose C++ only if that matches the user's intent.
- **Uncertain upload:** do not make a new submission. Inspect recent submissions and explicitly reconcile the operation to the matching ID.
- **Old verdict unavailable:** lookup is limited to five user status pages. Inspect the user's ACMP account directly.
- **CAPTCHA or session rejection:** complete supported verification on ACMP; the server does not bypass it.

No ChatGPT connection, app approval or catalog publication is implied by passing local MCP tests. [Publication limitations](PUBLICATION.md).
