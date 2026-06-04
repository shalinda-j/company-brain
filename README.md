# Company Brain 🧠

A **private, self-hosted second brain** for you and your AI agents. It stores
everything as plain Markdown (Obsidian-compatible), indexes it for **semantic
search**, and exposes it over a **REST API** and an **MCP server** so any AI
client (Claude Code, Cursor, …) can read from and write to the same shared
memory.

- **No GPU. No cloud LLM. No data leaves your box.** Embeddings run locally on
  CPU via [fastembed](https://github.com/qdrant/fastembed).
- **Multilingual** out of the box (Sinhala + English + code).
- **Portable** — the brain lives on one droplet; you connect from anywhere by
  carrying just a URL + API key.
- **Multi-agent** — every memory is tagged with the agent that wrote it, so
  agents can see what other agents have done. Saves tokens by recalling instead
  of re-deriving.

---

## How it works

```
            ┌──────────────────────────────────────────────┐
   AI tools │  Claude Code / Cursor / n8n / your web app    │
 (anywhere) └───────────────┬───────────────┬──────────────┘
                            MCP             REST (HTTPS + API key)
                             │               │
                  ┌──────────▼───────────────▼──────────┐
                  │            Brain API (FastAPI)        │   ← the droplet
                  │   save · search · get · recent ·      │
                  │   activity · reindex · delete         │
                  └───────┬───────────────────┬───────────┘
                          │                   │
              ┌───────────▼──────┐   ┌─────────▼─────────┐
              │  Markdown Vault  │   │  Qdrant (vectors) │
              │ (source of truth)│   │  (private network)│
              │  Obsidian-ready  │   │  semantic search  │
              └──────────────────┘   └───────────────────┘
```

The **Markdown vault is the source of truth**. Qdrant is a rebuildable index —
if it is ever lost, `reindex` regenerates it from the vault. You can open the
vault folder directly in Obsidian at any time.

---

## Quick start (DigitalOcean droplet)

A 2 vCPU / 4 GB droplet running Ubuntu 24.04 is plenty. No GPU.

```bash
git clone <your-repo-url> company-brain
cd company-brain
./install.sh
```

`install.sh` installs Docker if needed, generates strong API keys into `.env`,
and starts the stack. When it finishes it prints your base URL and key.

By default the API binds to `127.0.0.1:8000` (loopback only) and **Qdrant is
not exposed at all**. For remote access, enable HTTPS (next section).

### Enable HTTPS for remote access

1. Point a DNS `A` record (e.g. `brain.example.com`) at the droplet.
2. Add to `.env`:
   ```
   BRAIN_DOMAIN=brain.example.com
   ACME_EMAIL=you@example.com
   ```
3. Start with the TLS overlay (Caddy gets a Let's Encrypt cert automatically):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
   ```
4. Lock the firewall:
   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 80,443/tcp
   sudo ufw enable
   ```

---

## Connect your AI

The MCP server is the portable connector. It runs **wherever your AI client
runs** and talks to the brain over HTTPS. Install it locally:

```bash
pip install httpx mcp
# from the repo:
pip install -e .          # provides the `brain-mcp` command
```

### Claude Code / Claude Desktop / Cursor (MCP config)

```json
{
  "mcpServers": {
    "company-brain": {
      "command": "brain-mcp",
      "env": {
        "BRAIN_URL": "https://brain.example.com",
        "BRAIN_API_KEY": "YOUR_API_KEY",
        "BRAIN_AGENT": "claude-code"
      }
    }
  }
}
```

That is the whole "take it with you" story: copy this snippet to any machine,
fill in the URL + key, and that machine's AI is now connected to the same brain.
Give each client a different key so `BRAIN_AGENT` activity stays attributable.

### Tools the AI gets

| Tool | What it does |
|------|--------------|
| `brain_save` | Remember something (content, title, category, tags) |
| `brain_search` | Semantic search across all memories |
| `brain_get` | Read one memory in full by id |
| `brain_recent` | List the latest memories |
| `brain_activity` | See what each agent has been doing |

### Make it remember automatically

Add a line to your client's system prompt / project instructions, e.g.:

> At the end of any meaningful task, call `brain_save` with a short summary.
> Before starting research, call `brain_search` to reuse prior work.

For fully hands-off capture, pipe conversation logs to `POST /save` from an
**n8n** workflow (works great alongside an existing n8n droplet).

---

## REST API

All endpoints except `/health` require `Authorization: Bearer <key>`.

```bash
BASE=https://brain.example.com
KEY=YOUR_API_KEY

# save
curl -s -X POST $BASE/save -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"content":"Decided to use Qdrant + FastAPI","title":"Brain stack","category":"knowledge","tags":["infra"]}'

# search
curl -s -X POST $BASE/search -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"what stack did we pick for the brain","limit":5}'

# recent / activity / get / reindex
curl -s $BASE/recent -H "Authorization: Bearer $KEY"
curl -s "$BASE/activity?who=cursor" -H "Authorization: Bearer $KEY"
curl -s $BASE/get/<note_id> -H "Authorization: Bearer $KEY"
curl -s -X POST $BASE/reindex -H "Authorization: Bearer $KEY"
```

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness (no auth) |
| GET | `/stats` | Counts, model, mode |
| POST | `/save` | Store a memory |
| POST | `/search` | Semantic search |
| GET | `/get/{id}` | Fetch one memory |
| GET | `/recent?n=` | Latest memories |
| GET | `/activity?who=&n=` | Per-agent activity |
| POST | `/reindex` | Rebuild index from vault |
| DELETE | `/delete/{id}` | Remove a memory |

---

## Privacy & security

This was a first-class design goal.

- **Local embeddings.** Vectors are computed on-CPU; note text is never sent to
  any third party. The brain needs no external LLM to function.
- **Auth required, fail-closed.** If no keys are configured the authed routes
  return `503`. Keys map to an agent identity and are compared in constant time.
- **Keys never logged.** The audit log (`data/audit.log`) records the agent and
  action only — raw keys never appear in logs (verified by the test suite).
- **Qdrant is private.** It has no published ports; only the API reaches it over
  the internal Docker network.
- **API on loopback by default.** Remote exposure is opt-in and goes through
  Caddy with automatic HTTPS + HSTS and hardened headers.
- **Input hardening.** Pydantic validation, request-body size cap, rate
  limiting, locked-down CORS, and path-traversal-safe note ids.
- **Runs as non-root** inside the container.
- **Your data stays yours.** Everything lives under `data/` on your droplet:
  the Markdown vault, the Qdrant volume, and the audit log. `.env` and `data/`
  are git-ignored.

> If you ever pasted an API key somewhere public, rotate it: edit
> `BRAIN_API_KEYS` in `.env` and `docker compose up -d` again.

### Backup

Back up the vault (and optionally the Qdrant volume). The vault alone is enough
— the index rebuilds with `/reindex`.

```bash
tar czf brain-backup-$(date +%F).tgz data/vault
```

---

## Configuration

All settings are environment variables (see `.env.example`). Notable ones:

| Var | Default | Notes |
|-----|---------|-------|
| `BRAIN_API_KEYS` | — | `key:agent,key2:agent2` (required) |
| `EMBED_MODEL` | `paraphrase-multilingual-mpnet-base-v2` | swap for lighter MiniLM or e5-large |
| `LOG_SEARCHES` | `true` | save every query as a memory |
| `QDRANT_URL` | (compose sets it) | blank = embedded on-disk Qdrant |
| `RATE_LIMIT` | `120/minute` | per client IP |
| `CORS_ORIGINS` | empty | allowed browser origins |

### Embedding model choices

| Model | Dim | Trade-off |
|-------|-----|-----------|
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | fastest, lightest |
| `paraphrase-multilingual-mpnet-base-v2` (default) | 768 | balanced |
| `intfloat/multilingual-e5-large` | 1024 | best quality, heavier on CPU |

> Changing the model changes the vector size — run `POST /reindex` afterwards.

---

## Local development

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python tests/test_smoke.py        # runs end-to-end with a fake embedder
# run the API directly (embedded Qdrant):
BRAIN_API_KEYS="dev-key:me" uvicorn api.server:app --reload
```

## License

MIT — see [LICENSE](LICENSE).
