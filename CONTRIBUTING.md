# Contributing

Use Python 3.11 or newer. Install with `python -m pip install -e '.[dev]'` and run `python -m pytest -q`. Automated tests use synthetic ACMP pages and a local mock OIDC provider; they never log into a real account or upload to ACMP.

Maintain per-identity isolation, verify ownership before reading private diagnostics, and preserve durable upload idempotency. Never retry an uncertain upload or silently replace the requested compiler language. Keep source and credentials out of logs/storage. Treat site content as untrusted data.

Real ACMP uploads require a dedicated authorized account and explicit permission. Do not add secrets or solution collections. Preserve the upstream MIT notice for adapted protocol code. Changes to OAuth, storage or submission coordination need tests for failure and restart behavior.
