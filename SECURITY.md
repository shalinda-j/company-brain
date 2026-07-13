# Security Policy

Security is a first-class design goal of Company Brain. The brain is meant to
hold private notes and conversations, so we take reports seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's
[private vulnerability reporting](https://github.com/shalinda-j/company-brain/security/advisories/new),
or email the maintainer. Include:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- affected version / commit.

We aim to acknowledge reports within a few days and to ship a fix or mitigation
as quickly as is practical, then credit you (if you wish) in the release notes.

## Supported versions

The latest release (currently `0.2.x`) receives security fixes.

## Security model (what the project protects, and how)

- **Local embeddings.** Note text is embedded on-CPU and is never sent to a
  third party. The brain functions with no external LLM.
- **Authentication.** All endpoints except `/health` require a Bearer API key.
  If no keys are configured, authed routes fail closed (`503`). Keys are
  compared in constant time and map to an agent identity.
- **Per-key roles.** Keys use the format `key:agent:role` with role `admin`,
  `write`, or `read` (`key:agent` still works and defaults to `admin`). Give
  read-only clients a `read` key so a leaked key cannot alter memories.
- **No secret logging.** The audit log records the agent and action only. Raw
  API keys never appear in logs (enforced by a test).
- **Network isolation.** In the default Compose stack, Qdrant has no published
  ports and is reachable only by the API over the internal network. The API
  server itself defaults to `API_HOST=127.0.0.1` (loopback only) — remote
  exposure is an explicit opt-in.
- **Transport.** The optional Caddy overlay provides automatic HTTPS with HSTS
  and hardened headers. Prefer this (a real domain + Let's Encrypt) over a
  self-signed certificate on a bare IP: self-signed setups train clients to
  skip TLS verification (`BRAIN_VERIFY_TLS=false`), which enables MITM.
- **Input hardening.** Pydantic validation, request-body size cap (also
  enforced at the Caddy proxy, which chunked uploads cannot bypass), rate
  limiting, locked-down CORS, and path-traversal-safe note ids.
- **Redaction on by default.** Saves are scanned for secrets/PII and scrubbed
  before storage (`REDACT_ON_SAVE=true`).
- **Least privilege.** The API container runs as a non-root user.

## Operator responsibilities

- Generate strong keys (`python scripts/gen_key.py`); never commit `.env`.
- Use the TLS overlay (or your own reverse proxy with HTTPS) for remote access.
- Restrict the firewall to ports 22, 80, 443.
- Rotate any key that may have been exposed: edit `BRAIN_API_KEYS` and restart.
- Back up regularly: `make backup` (see README "Backup & Restore").
