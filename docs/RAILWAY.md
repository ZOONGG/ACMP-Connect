# Railway deployment

First private deployment and exact environment mapping: [Auth0 + Railway walkthrough (Russian)](PRIVATE_SETUP.ru.md).

The Docker image runs the official MCP SDK at `/mcp`, exposes `/healthz`, listens on Railway's `PORT`, and stores its database under `/data`. No public deployment has been performed.

## Infrastructure

Use one service, one replica and a persistent volume mounted at `/data`. Do not run multiple workers or overlapping replicas against this SQLite journal. Startup marks interrupted reservations uncertain; overlapping workers would invalidate that assumption. Stop the old instance before starting its replacement. Back up the database and encryption key separately.

Current [Railway configuration documentation](https://docs.railway.com/config-as-code) says new services cannot use legacy `railway.toml`/`railway.json`. This repository provides `.railway/railway.ts` using the current [IaC API](https://docs.railway.com/infrastructure-as-code/reference). It declares the service, volume, one replica, start command and healthcheck. Configure source and secrets privately. The template has not been applied or validated against a real Railway plan.

## Setup

1. With authorization to create billable resources, create a dedicated Railway service from this repository. Use the Dockerfile as build source.
2. Attach a persistent volume at `/data`, colocated with the service. Set `DATABASE_PATH=/data/acmp.sqlite3`. The container entrypoint prepares the directory and permanently drops to UID/GID 10001 before serving.
3. Configure a public HTTPS hostname. Set `PUBLIC_URL` to that exact origin without a trailing slash. Railway terminates HTTPS; the application serves internal HTTP and builds OAuth URLs from explicit configuration.
4. Fill `.env.example` variables in Railway's private variables UI. Keep `ACMP_DEV=0`. Preserve the encryption key across restarts. Never put secrets in IaC or Git.
5. Configure both OAuth/OIDC clients and exact callbacks in [AUTH.md](AUTH.md). Both clients must use the same stable user subject. This external setup cannot be replaced by an ACMP password.
6. Use `python -m acmp_connect.container_entrypoint` or the Docker entrypoint. Set healthcheck `/healthz`, timeout 60 seconds and one replica. The Railway healthcheck hostname is allowed; MCP still enforces its configured Host/Origin rules.
7. Deploy after reviewing the concrete resource plan. Check health, discovery, the MCP 401 challenge, browser linking and MCP Inspector/ChatGPT OAuth. Health alone does not prove provider configuration.

A Railway account connection was checked read-only. Existing unrelated projects were not modified. No paid service, volume, domain or public deployment was created.

## Operations

- Losing `SESSION_ENCRYPTION_KEY` makes saved sessions unreadable. Rotate through a controlled decrypt/re-encrypt migration or require reconnection.
- Use SQLite's backup API or stop the service for consistent backups; the main database alone can miss WAL data. Protect backups and keys separately.
- Interrupted uploads stay uncertain. Users inspect recent ACMP submissions and explicitly reconcile a matching ID. If no match exists, an operator must investigate; there is no automatic unblock-and-resubmit path.
- Local session TTL defaults to seven days; ACMP can expire sessions earlier. Users can disconnect or delete records.
- Healthchecks verify SQLite, not ACMP/provider uptime. Monitor external errors without logging credentials or source.
- Application access logs are disabled. Configure proxy/APM logging accordingly. Railway retains infrastructure data under its own policies.

## Local containers and verification

`docker build -t acmp-connect .` builds the image. Fill a private `.env`, then use `docker compose up -d` with a production HTTPS origin and a TLS proxy. For development HTTP, use the direct Python server with loopback `PUBLIC_URL` and `ACMP_DEV=1`; this mode binds to loopback and is not intended for container port forwarding.

A Linux image build, container startup, non-root serving, healthcheck and OAuth challenge were exercised locally. GitHub Actions includes a container smoke job. No GitHub Actions run, Railway deployment, external OAuth tenant flow or public HTTPS verification has been claimed.
