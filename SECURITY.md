# Security Policy

Security is a first-class design goal of Company Brain. The brain is meant to
hold private notes and conversations, so we take reports seriously.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via GitHub's
[private vulnerability reporting](https://github.com/USERNAME/company-brain/security/advisories/new),
or email the maintainer. Include:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- affected version / commit.

We aim to acknowledge reports within a few days and to ship a fix or mitigation
as quickly as is practical, then credit you (if you wish) in the release notes.

## Supported versions

The latest released `1.x` version receives security fixes.

## Security model (what the project protects, and how)

- **Local embeddings.** Note text is embedded on-CPU and is never sent to a
  third party. The brain functions with no external LLM.
- **Authentication.** All endpoints except `/health` require a Bearer API key.
  If no keys are configured, authed routes fail closed (`503`). Keys are
  compared in constant time and map to an agent identity.
- **No secret logging.** The audit log records the agent and action only. Raw
  API keys never appear in logs (enforced by a test).
- **Network isolation.** In the default Compose stack, Qdrant has no published
  ports and is reachable only by the API over the internal network. The API
  binds to `127.0.0.1` unless you explicitly enable the TLS overlay.
- **Transport.** The optional Caddy overlay provides automatic HTTPS with HSTS
  and hardened headers.
- **Input hardening.** Pydantic validation, request-body size cap, rate
  limiting, locked-down CORS, and path-traversal-safe note ids.
- **Least privilege.** The API container runs as a non-root user.

## Operator responsibilities

- Generate strong keys (`python scripts/gen_key.py`); never commit `.env`.
- Use the TLS overlay (or your own reverse proxy with HTTPS) for remote access.
- Restrict the firewall to ports 22, 80, 443.
- Rotate any key that may have been exposed: edit `BRAIN_API_KEYS` and restart.
- Back up the `data/vault` directory.
