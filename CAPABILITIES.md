# Company Brain — Capabilities (v0.0.1.3)

A multi-layer memory system reachable three ways: **Claude Code (MCP)**, the
**REST API**, and the **`brain` CLI**.

## Operations

| What you can do | MCP tool | REST API | CLI |
|---|---|---|---|
| Save a memory | `brain_save` | `POST /save` | `brain save` |
| Capture conversation text | `brain_ingest` | `POST /ingest` | `brain ingest` |
| Semantic search | `brain_search` | `POST /search` | `brain search` |
| **Multi-layer recall** | `brain_recall` | `POST /recall` | `brain recall` |
| Related memories | `brain_related` | `GET /related/{id}` | `brain related` |
| List graph entities | `brain_entities` | `GET /entities` | `brain entities` |
| Entity neighbors / notes | — | `GET /entities/{e}/neighbors`,`/notes` | — |
| Read SOUL | — | `GET /soul` | `brain soul` |
| Set SOUL | — | `POST /soul` | — |
| Teach a principle | `brain_learn` | `POST /soul/learn` | `brain learn` |
| Remember a preference | `brain_remember_preference` | `POST /preferences` | `brain pref` |
| Read preferences | — | `GET /preferences` | — |
| Tag taxonomy (ontology) | — | `GET/POST /ontology` | — |
| Read one memory | `brain_get` | `GET /get/{id}` | `brain get` |
| Latest memories | `brain_recent` | `GET /recent` | `brain recent` |
| Per-agent activity | `brain_activity` | `GET /activity` | `brain activity` |
| Mark a memory useful | `brain_feedback` | `POST /feedback` | `brain feedback` |
| List projects | `brain_projects` | `GET /projects` | `brain projects` |
| Consolidate duplicates | `brain_consolidate` | `POST /maintenance/consolidate` | `brain consolidate` |
| **Dream (reflect)** | `brain_dream` | `POST /maintenance/dream` | `brain dream` |
| Heartbeat tick | — | `POST /maintenance/tick` | `brain tick` |
| Rebuild index | — | `POST /reindex` | `brain reindex` |
| Delete a memory | — | `DELETE /delete/{id}` | — |
| **Hybrid search (dense + BM25)** | `brain_search` | `POST /search` (`hybrid`) | `brain search` |
| **Record a fact (bi-temporal)** | `brain_remember_fact` | `POST /facts` | `brain fact` |
| Current facts | `brain_facts` | `GET /facts` | `brain facts` |
| Fact history | — | `GET /facts/{subject}/history` | — |
| **Set a memory block** | `brain_set_block` | `POST /blocks` | `brain block` |
| Read memory blocks | — | `GET /blocks`, `/block/{name}` | — |
| Entity alias (resolution) | — | `POST /alias` | — |
| **Communities** | — | `GET /communities` | `brain communities` |
| Multi-hop traversal | — | `GET /entities/{e}/multihop` | — |
| Archive / unarchive | — | `POST /archive` | `brain archive` |
| **Doctor (audit)** | `brain_doctor` | `GET /doctor` | `brain doctor` |
| Export project | — | `GET /export` | `brain export` |
| Import project | — | `POST /import` | `brain import` |
| Ingest a file | — | — | `brain ingest-file`* |
| **Sleep cycle** | — | `POST /maintenance/sleep` | `brain sleep` |
| Retrieval eval (recall@k, MRR) | — | — | `brain eval` |
| Usage metrics | — | `GET /metrics` | `brain metrics` |
| Stats | — | `GET /stats` | `brain stats` |
| Liveness | — | `GET /health` | — |

**Categories**: `conversations`, `notes`, `tasks`, `knowledge`, `activity`,
`procedure`, `self`. Entities come from `[[wikilinks]]`, `#hashtags`, or the
explicit `entities` field on save.

## Memory layers (v3)

| Layer | What it is |
|---|---|
| **Semantic** | Vector search over your notes (multilingual, local CPU). |
| **Procedural** | `procedure` notes (how-tos), prioritized for "how to" queries. |
| **Knowledge graph** | Entities + co-occurrence relationships; query neighbors and notes. |
| **Document relationships** | Notes related by shared entities + similarity. |
| **Sense of self (SOUL)** | Per-project identity + learned principles, always recalled. |
| **Preferential** | Per-project key/value preferences, always recalled. |
| **Ontology** | Tag taxonomy that expands tag filters to descendant tags. |

## Intelligence behaviors

| Behavior | What it does |
|---|---|
| **Multi-layer recall** | One call assembles SOUL + preferences + memories + procedures + entities into a token-budgeted bundle. |
| **Dynamic priority weights** | "How-to" queries push procedures above memories; otherwise memories lead. |
| **Safe-learning (dedup)** | Near-identical memories aren't stored twice. |
| **Autonomous learning** | Accessing a memory raises its usefulness; unused memories decay over heartbeats. |
| **Dreaming** | Offline reflection: merge duplicates + synthesize digest notes from clusters. |
| **Heartbeat** | Optional background loop running decay + consolidation. |

> These are heuristic, local, and LLM-optional — a working foundation, not an
> autonomous AGI.

## Typical agent loop

```
Start of task →  brain_recall("the task")        # load SOUL + prefs + relevant context
During work   →  brain_search / brain_related    # pull specifics, follow relationships
Learned X     →  brain_learn("principle ...")     # durable self-knowledge
User prefs    →  brain_remember_preference(k, v)
End of task   →  brain_ingest("summary ...")      # remember what happened
Periodically  →  brain_dream()                    # reflect & tidy up
```


## What's new in v0.0.1.3

- **Hybrid retrieval**: dense vectors + BM25 keyword search, fused with RRF, then
  importance/usefulness-aware final ranking. Exact terms and rare codes surface
  reliably; meaning still matches loosely. `HYBRID_SEARCH=true`, `RRF_K=60`.
- **Bi-temporal facts**: facts that change over time. A new value for a subject
  supersedes (invalidates) the old one but keeps it as history — never deleted.
- **Secret / PII redaction**: saves are scanned for keys, tokens, private keys,
  and emails; reported in `pii_findings`, optionally scrubbed (`REDACT_ON_SAVE`).
- **Core memory blocks**: named, size-limited, editable context (e.g. `human`),
  always included in recall next to the SOUL.
- **Entity resolution**: alias map + normalization merge surface variants.
- **Communities + multi-hop**: cluster the entity graph and traverse it.
- **Importance, archival tiers, /doctor audit, export/import, file ingestion,
  per-user scoping, sleep cycle, eval harness, and metrics.**

### Optional (LLM) hooks — off by default
LLM triple extraction, LLM community summaries, and an LLM sleep-time reasoning
agent are documented hooks. Everything shipped here is local and deterministic.
For **encryption at rest**, use OS-level disk encryption (LUKS) so the vault
stays human-readable and git/Obsidian-friendly. A web dashboard is next.

\* `ingest-file` is CLI/in-process; there is also `ingest_dir` for folders.
