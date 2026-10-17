# Verification evidence

Verification date: 2026-10-16. No external deployment, GitHub Actions run or real ChatGPT OAuth connection is represented as tested.

## Real acmp.ru

- The provided account authenticated successfully. Numeric account identity was confirmed from the site's labeled account link plus independent logout evidence. The original failure was a false negative in the identity parser, not rejected credentials.
- Session cookies were serialized, restored into a fresh client and checked against the same account.
- Problems 1 (A+B) and 564 (Забор - 2) were read. Structured examples were extracted: one for problem 1 and two for problem 564.
- Both the exact topic URL and the natural-language query `Операторы цикла for` resolved to course 1, section 3, topic 33. Ten tasks were mapped; A is Монетки, archive problem 106.
- Recent submissions were read from the account's own status table.
- **One real C++ submission was made:** problem 1, submission **25641783**, compiler selection `CPP` (MinGW GNU C++ 15.2.0 offered by the site). It progressed from Compiling to **Accepted**, with 0.03 seconds and 330 KB reported by ACMP. [Actual submission page](https://acmp.ru/index.asp?main=source&id=25641783).
- Repeating the identical service call with the same idempotency key returned the stored result without another upload.
- A later read-only check confirmed that the source stored for submission 25641783 matches the uploaded source. Automatic attribution now requires this check in addition to a unique new status row; mismatches remain uncertain.
- An existing, account-owned Compilation error submission (25414356, previously submitted using Basic) was inspected read-only. ACMP exposes its compiler diagnostic text in the source/details page. Extraction was implemented for that real HTML shape. No deliberate failing upload was created.
- The actual form had C++ compiler options, but **no native C compiler**. A real C upload was not attempted or claimed.
- Real invalid-password, CAPTCHA, timeout and foreign-account scenarios were not induced on the site; automated tests cover those boundaries without extra external mutations.

Test-account credentials and raw cookies were not written into the repository. Temporary live-test session storage was encrypted and removed after testing.

## Automated tests

Run `python -m pytest -q`. Tests use synthetic ACMP HTML, controlled clients, and a local mock OIDC provider. They never contact ACMP or create real submissions.

The suite covers problem sections/examples/images; current and legacy identity layouts; rejected login and CAPTCHA responses; cookie roundtrip; redirect origin/scheme restrictions and blocked 307/308 POST replay; compiler selection for C and C++; unavailable native C; invalid IDs, language, encoding and source size; ID/verdict handling; pending timeouts and unknown statuses; strict account isolation; encrypted storage and key mismatch; account expiry; source matching; idempotency replay and key conflicts; concurrent reservations; crash recovery; cooldowns; ambiguous uploads and explicit reconciliation; disconnection and deletion; CSRF/Origin checks; OIDC state/nonce/PKCE; real RSA signatures and issuer/audience/expiry checks; MCP schemas, scopes, body limits, health and discovery.

The OIDC test provider uses actual RSA signing and a local JWKS HTTP endpoint. The browser flow runs through authorization redirect, callback token exchange, account linking and MCP access with the same subject. These are test identities, not an external production tenant.

The official MCP Python `ClientSession` and `streamable_http_client` also initialize, list tools and invoke `get_problem` over a real local Uvicorn TCP connection using a signed OAuth token.

Windows Python 3.14: **56 tests passed**. The final Linux Python 3.12 Docker image also passed **56 tests** (8.53 seconds), using the installed application package and the read-only mounted test suite. A Starlette warning concerns its test client's future HTTPX migration; no application test failure is hidden.

## Container and hosting

- Docker Desktop Linux engine built `acmp-connect:local` from the Dockerfile.
- The running container returned 200 from `/healthz` and 401 with protected-resource discovery from unauthenticated `/mcp`.
- The Docker healthcheck command succeeded. `/proc/1/status` confirmed UID/GID 10001 and umask 0077.
- A container restart completed. Persistent application state and interrupted reservations are additionally exercised by automated storage tests.
- Railway's connected account was listed successfully, read-only. No existing project was changed and no new resource/domain/deployment was created.
- GitHub Actions defines Python 3.11–3.14 and container jobs, but those hosted jobs have not been run.

## External work still required

Configure an established OAuth/OIDC tenant and both clients, including stable cross-client subjects and MCP resource binding. Approve and deploy an HTTPS host with a persistent volume. Verify the real provider and ChatGPT connection. Test desktop/mobile surfaces separately if needed. Official directory distribution additionally requires resolving the current prohibition on unofficial connectors and appropriate ACMP authorization; see [PUBLICATION.md](PUBLICATION.md).
