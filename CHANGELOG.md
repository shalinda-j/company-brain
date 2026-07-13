# Changelog

All notable changes are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-07-13 — Audit release: security, retrieval, and ops fixes

> Versioning note: earlier releases ran 1.0.0 → 2.0.0 → 3.0.0 → 0.0.1.x without
> a consistent scheme. Numbering restarts at **0.2.0** and follows SemVer from
> here on.

### Fixed
- **Retrieval ranking**: corrected the score blend so relevance is no longer
  drowned out by usefulness/access boosts.
- **Search-log feedback loop**: logged searches (`LOG_SEARCHES`) no longer feed
  back into ranking as ordinary memories.
- **Atomic writes**: vault notes are written atomically (write-temp + rename),
  so a crash can no longer leave a truncated note.
- **Consolidation archives, never deletes**: duplicate merging now archives the
  losing notes instead of destroying them.
- **install.sh**: the health wait loop now exits non-zero on timeout, and the
  openssl fallback key generator emits valid `key:agent` format.

### Added
- **Per-key roles**: `BRAIN_API_KEYS` accepts `key:agent:role` with role
  `admin` / `write` / `read`. Plain `key:agent` still works (defaults to
  `admin`).
- **Session close + promotion**: `POST /session/close` (and
  `Brain.close_session`) summarizes a session's checkpoints into a promoted
  memory note.
- **Recency decay**: search ranking now decays stale memories over time.
- **Per-project caching** for hot lookups.
- **MCP**: `delete` / `archive` / `pin` tools, plus a `--check` startup flag to
  verify connectivity.
- **Backup script**: `scripts/backup.sh` (and `make backup`) tars the vault +
  audit log with timestamped, pruned archives. See README "Backup & Restore".
- **Release automation**: `v*` tags build and push
  `ghcr.io/shalinda-j/company-brain` and create a GitHub Release.

### Changed
- **Redaction on by default**: `REDACT_ON_SAVE` now defaults to `true`, with
  new token patterns (GitHub, Slack, Google, JWT).
- **Real rate limiting**: the per-IP limit is actually enforced across workers.
- **API binds to `127.0.0.1` by default** (`API_HOST`); remote exposure is
  opt-in via the Caddy TLS overlay.
- **Qdrant pinned** to `qdrant/qdrant:v1.12.6` with a healthcheck; the API
  waits for it to be healthy.
- **Caddy enforces a 10 MB request-body cap** at the proxy (chunked uploads
  can bypass app-level Content-Length checks).

## [0.0.1.6] - 2026-06-06 — Real-time session checkpoints (crash recovery)

Continuously capture "what am I doing right now" so a crash never loses your
place. All local + tested (91 tests, ruff-clean).

### Added
- **Session / checkpoint layer** (`brain/session.py`): append-only, cheap,
  timestamped checkpoints stored under `_sessions/<session>.jsonl` — a reserved
  dir that is **never embedded or indexed**, so high-frequency writes do not
  pollute semantic recall.
  - `checkpoint(note, session, files, git_ref, next, status)` /
    `POST /checkpoint` / `brain_checkpoint` / CLI `checkpoint`.
  - `resume(session?)` / `GET /resume` / `brain_resume` / CLI `resume` — recover
    the latest checkpoints ("where was I", which files, what's next, git ref).
  - `sessions()` / `GET /sessions` / CLI `sessions` — list session journals.
  - Checkpoints run through secret/PII **redaction** (honours `REDACT_ON_SAVE`).
- **Git auto-snapshot daemon** (`scripts/brain-autosnapshot.sh`): a feeder that
  periodically takes a **non-destructive** snapshot (`git stash create`, working
  tree untouched), saves it under `refs/snapshots/<session>/<epoch>`, and posts a
  checkpoint with the snapshot SHA + changed files — so you recover **both**
  context (brain) and exact file state (`git stash apply <sha>`).
- **VS Code extension (0.0.2)**: opt-in `companyBrain.autoCheckpoint` records a
  checkpoint when you save files; new **"Company Brain: Resume (where was I)"**
  command shows your latest checkpoints and offers to copy the git restore
  command.

### Feeders (how real-time data gets in)
The brain stores + serves checkpoints; events come from any of: the AI agent
calling `brain_checkpoint` each step, the git auto-snapshot daemon, or the VS
Code autosave hook. Use one or several together.

## [0.0.1.5] - 2026-06-06 — Directives, recall transparency, per-agent identity

Addresses three design gaps (raised in community feedback). All local + tested
(85 tests, ruff-clean).

### Added
- **Always-applied directives (pinned tier)** — `add_directive` / `POST /directives`
  / `brain_add_directive` / CLI `directive`, plus pinning any note via
  `POST /pin` (CLI `pin`, `set_pinned`). Pinned notes form a **Directives** layer
  that is injected into **every recall regardless of the query**, so a rule like
  "never deploy on Fridays" is never missed (previously it landed in the semantic
  layer and competed for top-k slots).
- **Recall transparency** — `recall()` now returns `included_layers` and
  `dropped_layers`, so callers can see exactly what was assembled vs omitted under
  the token budget (no more silent drops). SOUL, directives, and facts are
  **guaranteed layers** — protected from being dropped ahead of memories.
- **Per-agent identity** — SOUL, preferences, and memory blocks now support
  optional **per-agent overlays** (`_souls/<agent>.md`, `_prefs/<agent>.md`,
  `_blocks/<agent>/`). Recall **merges shared + the requesting agent's overlay**,
  so one agent's learned principle no longer rewrites every agent's identity. Set
  `agent_scope=true` on `/soul`, `/soul/learn`, `/preferences`, `/blocks`
  (MCP/CLI: `personal=True` / `--personal`).
- **Per-agent fact reconciliation** — fact invalidation is now scoped by
  `(subject, predicate, agent)`, so agents no longer clobber each other's facts
  (last-write-wins is now per-agent). Cross-agent disagreements are **surfaced**
  as `fact_contradictions` (with the asserting `agents`) by `/doctor` instead of
  silently overwriting.

### Changed
- `recall` accepts an `agent` argument and assembles **8 layers** (SOUL ·
  directives · blocks · preferences · facts · memories · procedures · entities).
- Notes gain a `pinned` field; `directive` is a new category.

## [0.0.1.4] - 2026-06-05 — Graph endpoint + dashboard

### Added
- **`GET /graph`**: nodes + edges for a force-directed dashboard graph. `mode=entities`
  returns the knowledge graph (entities as nodes, co-occurrence edges, colored by
  community); `mode=notes` returns an Obsidian-style note graph (notes as nodes,
  edges from explicit links + shared entities). Powers the VS Code extension and
  the standalone dashboard.

## [0.0.1.3] - 2026-06-05 — Retrieval, facts, and safety

This release brings Company Brain in line with current SOTA agent-memory systems
(mem0, Zep/Graphiti, Letta/MemGPT, Microsoft GraphRAG, Qdrant hybrid search). All
features below are fully local and tested (73 tests, ruff-clean). LLM-dependent
parts are documented optional hooks, not hard requirements.

### Added
- **Hybrid retrieval**: dense (vector) + BM25 (keyword) results fused with
  Reciprocal Rank Fusion (RRF). Exact keywords, codes, and rare terms now surface
  reliably alongside semantic matches. Toggle with `HYBRID_SEARCH` / `RRF_K`, or
  per-call (`hybrid` on `/search`). Importance-aware final ranking.
- **Bi-temporal facts** (`/facts`, `brain_remember_fact`, `brain_facts`): facts
  carry `valid_from`/`valid_to` + `ingested_at`/`invalidated_at`. Recording a new
  value for the same subject **invalidates** the prior fact instead of deleting
  it (full history via `/facts/{subject}/history`). Handles "facts change".
- **Secret / PII redaction** (`brain.redact`): every save is scanned for AWS keys,
  Anthropic/OpenAI keys, private-key blocks, bearer tokens, `key=…` assignments,
  emails, and high-entropy tokens. Findings are returned in `pii_findings`; with
  `REDACT_ON_SAVE=true` they are scrubbed before storage.
- **Core memory blocks** (`/blocks`, `brain_set_block`): named, size-limited,
  self-editable context units (e.g. a `human` block). Always injected into recall
  alongside the SOUL (persona). Cap via `BLOCK_CHAR_LIMIT`.
- **Entity resolution** (`/alias`): normalization + an explicit alias map collapse
  surface variants ("qdrant db" → "Qdrant") into one graph node.
- **Communities + multi-hop**: label-propagation community detection
  (`/communities`) and BFS graph traversal (`/entities/{e}/multihop`).
- **Importance scoring**: every memory gets a write-time salience score (1–5,
  heuristic or explicit), used in ranking and shown in activity.
- **Archival tiers** (`/archive`): archive/unarchive memories; archived items are
  excluded from default search/recall/recent but retrievable with
  `include_archived`.
- **/doctor audit** (`/doctor`, `brain_doctor`): reports duplicate pairs, stale
  items, orphan entities, oversized blocks, possible secrets/PII, and
  contradictory facts.
- **Export / import** (`/export`, `/import`): portable JSON bundle of a project's
  notes + SOUL + blocks + preferences + facts (backup/restore, project cloning).
- **File ingestion**: `ingest_file` / `ingest_dir` (CLI `ingest-file`) capture
  text/markdown/code files as memories.
- **Per-user scoping**: optional `user` field on save + `user` filter on
  search/recall for multi-user isolation within a project.
- **Sleep cycle** (`/maintenance/sleep`, CLI `sleep`): a fuller maintenance pass —
  dream + optional archival of stale low-value memories + a health summary.
- **Eval harness** (`brain.evaluate`, CLI `eval`): recall@k + MRR over a small
  dataset, so retrieval changes can be measured. Sample at `eval/sample.json`.
- **Metrics** (`/metrics`, CLI `metrics`): in-process usage counters.

### Notes / honest scope
- **Optional LLM hooks (not required, off by default)**: LLM-based triple
  extraction for the graph, LLM community *summaries*, and an LLM-driven
  sleep-time reasoning agent. The algorithmic pieces (heuristic extraction,
  community *detection*, dream/sleep maintenance) are fully implemented and local.
- **Encryption at rest**: recommend OS-level disk encryption (e.g. LUKS) so the
  Markdown vault stays human-readable, git-friendly, and Obsidian-compatible.
  Application-level field encryption is intentionally not enabled; secret/PII
  redaction is the in-app control.
- **Web dashboard**: deferred to the next milestone.

### Changed
- `search`/`recall` accept `user`, `include_archived`, and `hybrid`.
- Recall now assembles **7 layers** (SOUL · blocks · preferences · facts ·
  memories · procedures · entities) with dynamic reordering and a token budget,
  and includes current facts for entities mentioned in the query.
- `ingest` tags episodes `episode` (plus the existing `ingested`).
- Reserved paths: any file/dir beginning with `_` (e.g. `_SOUL.md`, `_blocks/`,
  `_FACTS.json`) is never treated as an ordinary memory.

## [3.0.0] - 2026-06-04 — Multi-layer memory

### Added
- **Knowledge graph layer**: entities are extracted from `[[wikilinks]]`,
  `#hashtags`, and an explicit `entities` field. Query entities, their
  neighbors (co-occurrence), and the notes that mention them
  (`/entities`, `brain_entities`).
- **Document relationships**: `/related/{id}` (and `brain_related`) surface
  memories related by shared entities + semantic similarity.
- **SOUL (sense of self)**: a per-project, human-editable self-context document
  (`/soul`). Agents append durable learned principles (`/soul/learn`,
  `brain_learn`) that appear in every recall.
- **Preferential context**: per-project key/value preferences (`/preferences`,
  `brain_remember_preference`), surfaced in every recall.
- **Procedural memory**: a first-class `procedure` category, prioritized in
  recall for "how-to" queries.
- **Multi-layer recall**: `/recall` (and `brain_recall`) assembles SOUL +
  preferences + relevant memories + procedures + related entities into one
  context bundle, with **dynamic priority weights** (procedure-style queries
  reorder layers) and a **token budget**.
- **Dreaming**: `/maintenance/dream` (and `brain_dream`) reflects offline —
  consolidates duplicates and synthesizes digest notes from clusters of related
  memories (LLM-optional).
- **Heartbeat**: an optional background scheduler (`HEARTBEAT_INTERVAL`) plus a
  manual `/maintenance/tick` that runs usefulness decay + consolidation.
- **Autonomous learning**: accessing a memory raises its usefulness
  (`access_count`); unused memories decay over heartbeats; explicit feedback
  still applies. Search ranking blends similarity + usefulness + access.
- **Ontology**: a tag taxonomy (`/ontology`) that expands a tag filter to its
  descendant tags during search.
- New CLI commands: `recall`, `related`, `entities`, `soul`, `learn`, `pref`,
  `dream`, `tick`.

### Notes
- These layers are heuristic and local (LLM-optional) — a real, working
  foundation, not an autonomous AGI. "Mathematical relationships" from the
  inspiring multi-layer-memory discussion are intentionally out of scope.

## [2.0.0] - 2026-06-04
### Added
- Projects (isolated vault + collection), conversation ingest, safe-save
  deduplication, feedback re-ranking, consolidation, and matching CLI commands.
### Fixed
- Data-dir permission bug (entrypoint now fixes ownership via `gosu`).
- Vector dimension-mismatch crash (auto-rebuild + re-index on model change).
### Changed
- Lighter default embedding model; installer adds swap on low-RAM hosts.

## [1.0.0] - 2026-06-04
### Added
- Markdown vault, local CPU embeddings, Qdrant store, REST API, MCP server, CLI,
  multi-agent identity, API-key auth + audit log, Docker deploy with optional
  Caddy HTTPS, one-command installer, offline tests, and CI.

[Unreleased]: https://github.com/shalinda-j/company-brain/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/shalinda-j/company-brain/releases/tag/v0.2.0
[3.0.0]: https://github.com/shalinda-j/company-brain/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/shalinda-j/company-brain/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/shalinda-j/company-brain/releases/tag/v1.0.0
