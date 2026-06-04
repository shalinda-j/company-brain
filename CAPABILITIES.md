# Company Brain — Capabilities

Everything the brain can do, across the three ways to reach it: **Claude Code
(MCP)**, the **REST API** (curl / any app / n8n), and the **`brain` CLI**.

## Core operations

| What you can do | MCP tool | REST API | CLI |
|---|---|---|---|
| Save a memory | `brain_save` | `POST /save` | `brain save` |
| Capture conversation text | `brain_ingest` | `POST /ingest` | `brain ingest` |
| Search by meaning (semantic) | `brain_search` | `POST /search` | `brain search` |
| Read one memory in full | `brain_get` | `GET /get/{id}` | `brain get` |
| List newest memories | `brain_recent` | `GET /recent` | `brain recent` |
| See what each agent did | `brain_activity` | `GET /activity` | `brain activity` |
| Mark a memory useful | `brain_feedback` | `POST /feedback` | `brain feedback` |
| List all projects | `brain_projects` | `GET /projects` | `brain projects` |
| Merge duplicate memories | `brain_consolidate` | `POST /maintenance/consolidate` | `brain consolidate` |
| Rebuild index from vault | — | `POST /reindex` | `brain reindex` |
| Delete a memory | — | `DELETE /delete/{id}` | — |
| Stats (per project) | — | `GET /stats` | `brain stats` |
| Liveness (no auth) | — | `GET /health` | — |

**Save fields**: `content` (required), `title`, `category`, `tags`, `source`,
`project`, `allow_duplicate`.
**Categories**: `conversations`, `notes`, `tasks`, `knowledge`, `activity`.
**Search fields**: `query`, `limit` (1–50), `category`, `agent`, `tag`, `project`.

## Capabilities (v2)

| Capability | What it means |
|---|---|
| **Projects** | Each project (`avedit`, `weddinghub`, …) is fully isolated: its own vault folder and vector collection. Searching one project never returns another's memories. |
| Shared multi-agent memory | Claude Code, Cursor, etc. read/write the same brain; every entry is tagged by agent. |
| Cross-session / cross-machine | Connect from anywhere with URL + key; nothing heavy stored locally. |
| Semantic, multilingual recall | Find by meaning in Sinhala + English + code. |
| **Safe-learning (dedup on save)** | A near-identical memory is recognized, not stored twice. Override with `allow_duplicate`. |
| **Feedback re-ranking** | Mark memories useful; useful memories rank higher in future searches. |
| **Self-optimization (consolidation)** | Periodically merge near-duplicate memories into one. |
| **Conversation ingest** | Capture chat text as memories; optional off-by-default LLM summarization. |
| Agent coordination | `brain_activity` shows what other agents already did. |
| Auto search-logging | Every query is saved as an `activity` memory. |
| Obsidian-browsable | The vault is plain Markdown per project — open in Obsidian, version with git. |
| Private & self-hosted | Embeddings run locally on CPU; nothing leaves your droplet. |
| Resilient | A vector-dimension mismatch (after switching models) auto-rebuilds and re-indexes. |

## Auto-capturing conversations

The brain is pull-based: an AI calls `brain_ingest` / `brain_save` when it
decides to. To capture automatically, either:

1. **Instruct the agent** — in Claude Code project instructions:
   > At the end of each task, call `brain_ingest` with a short summary of what
   > was decided or done, using the right `project`.
2. **Pipe from n8n** — `POST /ingest` with conversation logs from a workflow.

## Examples

```bash
export BRAIN_URL=https://your-brain BRAIN_API_KEY=KEY BRAIN_VERIFY_TLS=false

brain save "Use Qdrant + FastAPI" --project avedit --category knowledge --tag infra
brain search "what stack did we choose" --project avedit
brain ingest "We agreed to ship the MVP next week and use PayHere." --project weddinghub
brain feedback 20260604-120909-abc123 --project avedit
brain consolidate --project avedit
brain projects
```

In Claude Code, just talk: *"save this to my avedit brain…"*, *"search my
weddinghub brain for payments"*, *"what did the cursor agent do in avedit?"*.
