# ACMP Connect

A multi-user Python MCP server connecting ChatGPT to [acmp.ru](https://acmp.ru). ChatGPT reads the exact problem, writes the solution itself, submits it on explicit request, and checks the real judge verdict. No paid AI API is used.

**Status:** local implementation and live ACMP C++ submission verified. External OAuth tenant configuration and a public HTTPS deployment are still required before connecting ChatGPT. This is an independent integration, not affiliated with ACMP or OpenAI. Official directory publication is blocked by the current policy on unofficial third-party connectors; see [publication notes](docs/PUBLICATION.md).

[Русская инструкция](docs/README.ru.md) · [ChatGPT setup](docs/CHATGPT.md) · [Account linking and OAuth](docs/AUTH.md) · [Railway](docs/RAILWAY.md) · [Test evidence](docs/TESTING.md) · [Privacy](docs/PRIVACY.md)

## Tools

| Tool | Purpose | Scope |
| --- | --- | --- |
| `get_problem` | Exact statement, constraints, sections, samples and image URLs | `acmp:read` |
| `get_topic` | Map topic letters to archive IDs; name search in course 1, URL for other courses | `acmp:read` |
| `get_account_status` | Check session and return the secure linking URL | `acmp:read` |
| `submit_solution` | One explicit C/C++ submission, with a durable idempotency key | `acmp:submit` plus read |
| `get_verdict` | Actual verdict, failing test, time, memory, compiler log when available | `acmp:read` |
| `get_my_submissions` | Recent submissions from the linked account | `acmp:read` |
| `reconcile_submission` | Associate an uncertain operation with a user-selected existing submission | `acmp:submit` plus read |
| `disconnect_account` | Disconnect cookies or delete local user records | `acmp:manage` plus read |

Every MCP request requires OAuth. Public problem data does not require linking an ACMP account. Output schemas, security metadata and MCP annotations are provided by the official Python MCP SDK. Transport: stateless Streamable HTTP at `/mcp`.

## Install and run

Python 3.11+:

```sh
python -m venv .venv
# Activate .venv for your shell.
python -m pip install -e '.[dev]'
python -m pytest -q
```

Copy `.env.example` to a private `.env`, fill the OAuth and encryption settings according to [AUTH.md](docs/AUTH.md), and load it into the process environment. Never commit `.env`.

```sh
python -m dotenv -f .env run -- acmp-server
```

Alternatively use `docker compose up --build` after configuring `.env`. The server fails closed if its mandatory configuration is missing. `ACMP_DEV=1` permits HTTP only for loopback URLs, binds the direct Python server to loopback, and relaxes cookie Secure flags for local development; it does **not** disable authentication. Leave it at `0` for hosting.

For a dotenv installation without its optional CLI, set variables using your shell or run `python -m pip install 'python-dotenv[cli]'`. Docker Compose reads `.env` directly.

## CLI

The original CLI is retained:

```sh
acmp-connect task 564
# Set ACMP_LOGIN and ACMP_PASSWORD privately for this process only:
acmp-connect submit 1 solution.cpp --confirm
```

The CLI keeps cookies in memory. Its one-process submission tracking is simpler than the server's persistent idempotency journal; use the MCP server for multi-user operation. Never place credentials in chat, command arguments, source files or Git. C is accepted as an input language, but it is refused when the current ACMP form has no genuine C compiler. On 2026-10-16 only C++ compilers were available for C-family submissions.

## Reliability and limitations

- Uploads are never automatically retried. Reuse an idempotency key for the same explicit action; new keys require new user intent.
- SQLite transactions serialize reservations per linked ACMP account. A crash or unknown POST outcome blocks further uploads until explicit reconciliation. No speculative resubmission is performed.
- A 30-second local submission cooldown is additional to ACMP's limits. CAPTCHA, rate limits and session expiry are surfaced to the user.
- Avoid simultaneous submissions through another browser/client. If multiple new rows appear, automatic attribution stops.
- A single new row is confirmed only after its stored ACMP source matches the uploaded source. Inaccessible or mismatched source leaves the operation uncertain.
- Verdict lookup scans at most five ACMP status pages (about 100 recent submissions). Older records may be unavailable through this tool. No global table is used to bypass ownership checks.
- Compiler errors are read only after matching a submission in the linked user's status table. Missing logs remain unavailable; no judge data is invented.
- Topic name discovery covers course 1 and at most 40 sections; topic resolution is capped at 60 problems. Use an exact URL for other courses or ambiguous names. ACMP HTML is not a stable official API.
- A true C compiler was unavailable during live tests; C multipart selection is covered by mocks. Mobile and desktop ChatGPT access depends on product/workspace availability; only the documented web setup is claimed.
- One process, one replica and one persistent SQLite volume are required. Horizontal scaling needs a shared database/locking migration.

## Architecture

`client.py` retains the original HTTP/CLI parsing. `acmp_client.py` adds structured problem, topic, session and diagnostics operations. `auth.py` validates RS256 OAuth JWTs against an established issuer. `portal.py` uses OIDC authorization code + PKCE to authenticate the account-linking page. `storage.py` encrypts cookies and temporary browser state with Fernet and keeps a durable operation journal. `service.py` enforces user/account ownership and upload reservations. `mcp_server.py` exposes the tools and HTTP endpoints.

There is no ACMP OAuth implementation: the external identity provider authenticates the plugin user; ACMP login/password is accepted only on the authenticated connection page and immediately exchanged for cookies.

## License

MIT. The original ACMP HTTP/multipart protocol code was adapted from [hanglider/ACMP/tools/acmp.py](https://github.com/hanglider/ACMP/blob/main/tools/acmp.py); its copyright notice is preserved in [LICENSE](LICENSE). No solution collection is included. ACMP task statements, images and third-party branding are not licensed by this repository's MIT license.
