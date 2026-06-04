# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-06-04

### Added
- **Projects**: every memory is scoped to a project, each with its own vault
  subfolder and its own vector collection — fully isolated search. New
  `GET /projects`, `--project` everywhere, `BRAIN_PROJECT` for clients, and a
  `brain_projects` MCP tool.
- **Conversation ingest**: `POST /ingest` and the `brain_ingest` tool capture
  conversation text as memories (with optional, off-by-default LLM
  summarization via `BRAIN_SUMMARIZE`).
- **Safe-learning guardrail**: near-duplicate detection on save — an
  almost-identical memory is recognized instead of stored twice
  (`SAFE_SAVE`, `DEDUP_THRESHOLD`, `allow_duplicate` override).
- **Feedback re-ranking**: `POST /feedback` and `brain_feedback` adjust a
  memory's usefulness; search blends usefulness into the ranking
  (`FEEDBACK_WEIGHT`).
- **Self-optimization / consolidation**: `POST /maintenance/consolidate` and
  `brain_consolidate` merge near-duplicate memories within a project.
- **CLI** gains `ingest`, `feedback`, `consolidate`, `projects`, and
  `--project` on all relevant commands.

### Fixed
- **Permission bug**: a root-owned bind-mounted `./data` made the non-root
  container fail on startup. A new entrypoint fixes ownership and drops
  privileges via `gosu`, so a host-mounted data dir always works.
- **Dimension-mismatch crash**: switching `EMBED_MODEL` against an existing
  collection caused hard failures. The store now detects a vector-size mismatch
  and automatically rebuilds the collection and re-indexes that project's vault.

### Changed
- Default embedding model is now the lighter multilingual
  `paraphrase-multilingual-MiniLM-L12-v2` (fits 2 GB droplets).
- `install.sh` adds a swapfile on low-RAM hosts to prevent OOM during model load.

## [1.0.0] - 2026-06-04

### Added
- Markdown vault (Obsidian-compatible), local CPU embeddings via fastembed,
  Qdrant vector store (server or embedded), REST API, MCP server, and `brain`
  CLI. Multi-agent identity, optional search-logging, API-key auth with audit
  logging, Docker/compose deploy with optional Caddy HTTPS, one-command
  `install.sh`, offline test suite, and GitHub Actions CI.

[Unreleased]: https://github.com/USERNAME/company-brain/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/USERNAME/company-brain/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/USERNAME/company-brain/releases/tag/v1.0.0
