"""The Brain (v0.0.1.3): a multi-layer memory system.

Layers: semantic notes, procedures, a knowledge graph (entities + relationships,
communities, multi-hop), document relationships, bi-temporal facts, a sense of
self (SOUL + core memory blocks), and preferences. Behaviors: hybrid retrieval
(dense + BM25 fused with RRF), multi-layer recall with dynamic weights + token
budget, importance-aware ranking, dreaming, a heartbeat, autonomous (access-based)
learning, archival tiers, a /doctor audit, and secret/PII redaction.

Heuristic and local (LLM-optional). The Markdown vault is the source of truth;
the vector index, graph, facts, and blocks are rebuildable / portable.
"""

from __future__ import annotations

import calendar
import json
import logging
import math
import threading
import time
from collections import Counter

from qdrant_client.models import FieldCondition, Filter, MatchValue

from . import (
    blocks,
    facts,
    graph,
    hybrid,
    ontology,
    preferences,
    redact,
    resolve,
    session,
    soul,
    vault,
)
from .chunking import chunk_text
from .config import config
from .embeddings import get_embedder
from .store import VectorStore
from .summarize import maybe_summarize

_PROCEDURE_CUES = (
    "how ",
    "how to",
    "steps",
    "step by step",
    "setup",
    "set up",
    "deploy",
    "install",
    "configure",
    "guide",
    "procedure",
    "process",
)

_log = logging.getLogger("brain")

# Directories skipped by ingest_dir (any path containing one of these parts).
_INGEST_IGNORE = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}

_TEXT_EXTS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".csv",
    ".html",
    ".yaml",
    ".yml",
    ".sh",
}


class Brain:
    def __init__(self):
        config.ensure_dirs()
        self._lock = threading.RLock()
        self.embedder = get_embedder(config.embed_model, config.embed_cache_dir)
        self._stores: dict[str, VectorStore] = {}
        # project -> (notes_by_id, bm25_index); popped on every write path.
        self._corpus_cache: dict[str, tuple[dict, dict]] = {}
        self._corpus_gen: dict[str, int] = {}
        self._metrics: Counter = Counter()
        for project in vault.list_projects():
            self._get_store(project)

    # -- store management ------------------------------------------------
    def _get_store(self, project: str) -> VectorStore:
        project = vault.sanitize_project(project)
        with self._lock:
            store = self._stores.get(project)
            if store is None:
                store = VectorStore(config.collection_for(project), dim=self.embedder.dim)
                self._stores[project] = store
                try:
                    if store.count() == 0 and any(True for _ in vault.iter_notes(project)):
                        self._reindex_project(project, store)
                except Exception as exc:
                    _log.warning("lazy reindex of project %r failed: %s", project, exc)
            return store

    def _index_note(self, store: VectorStore, note) -> int:
        chunks = chunk_text(note.content, config.chunk_size, config.chunk_overlap)
        if not chunks:
            chunks = [note.title]
        vectors = self.embedder.embed_documents(chunks)
        store.upsert_note(note, vectors, chunks)
        return len(chunks)

    def _reindex_project(self, project: str, store: VectorStore) -> int:
        n = 0
        for note, _ in vault.iter_notes(project):
            self._index_note(store, note)
            n += 1
        return n

    # -- corpus cache / metadata-only index updates ----------------------
    def _corpus(self, project: str) -> tuple[dict, dict]:
        """(notes_by_id, bm25_index) for a project, cached until a write pops it.

        ponytail: no cache lock — a rebuild that loses the generation race is
        still returned to its caller, just not cached, so no stale snapshot
        can be pinned; edits made to vault files outside this process stay
        stale until the next write or restart."""
        cached = self._corpus_cache.get(project)
        if cached is None:
            gen = self._corpus_gen.get(project, 0)
            notes_by_id = {n.id: n for n, _ in vault.iter_notes(project)}
            docs = [(n.id, f"{n.title}\n{n.content}") for n in notes_by_id.values()]
            cached = (notes_by_id, hybrid.bm25_index(docs))
            if self._corpus_gen.get(project, 0) == gen:  # no write mid-rebuild
                self._corpus_cache[project] = cached
        return cached

    def _invalidate_corpus(self, project: str) -> None:
        self._corpus_gen[project] = self._corpus_gen.get(project, 0) + 1
        self._corpus_cache.pop(project, None)

    def _set_payload(self, project: str, note_id: str, payload: dict) -> None:
        """Update index payload fields (counters/flags) without re-embedding."""
        store = self._get_store(project)
        try:
            store.client.set_payload(
                store.collection,
                payload=payload,
                points=Filter(
                    must=[FieldCondition(key="note_id", match=MatchValue(value=note_id))]
                ),
            )
        except Exception as exc:
            _log.warning("payload update for note %s failed: %s", note_id, exc)

    @staticmethod
    def _age_days(ts: str) -> float | None:
        try:
            then = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
        except (TypeError, ValueError):
            return None
        return max(0.0, (time.time() - then) / 86400.0)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _importance(content: str, category: str, entities: list[str], explicit: int | None) -> int:
        if explicit is not None:
            return max(1, min(int(explicit), 5))
        score = 1
        if entities:
            score += 1
        if category in ("knowledge", "procedure", "self"):
            score += 1
        if len(content or "") >= 400:
            score += 1
        return min(score, 5)

    def _hit(self, note, score: float) -> dict:
        return {
            "note_id": note.id,
            "title": note.title,
            "text": (note.content or "")[:240],
            "category": note.category,
            "agent": note.agent,
            "tags": note.tags,
            "score": round(float(score), 4),
            "usefulness": note.usefulness,
            "access_count": note.access_count,
            "importance": note.importance,
            "archived": note.archived,
            "updated": note.updated,
        }

    def _final_rank(self, hits: list[dict]) -> list[dict]:
        wu, wa = config.feedback_weight, config.access_weight
        wr, half_life = config.recency_weight, config.recency_half_life_days
        for h in hits:
            boost = wu * (math.log1p(max(h.get("usefulness", 0), 0)) / math.log1p(10))
            boost += wa * (math.log1p(max(h.get("access_count", 0), 0)) / math.log1p(10))
            boost += 0.05 * (max(h.get("importance", 1), 1) - 1)
            age = self._age_days(h.get("updated") or "")
            if age is not None and wr > 0 and half_life > 0:
                boost += wr * 0.5 ** (age / half_life)
            h["final_score"] = round(float(h.get("score", 0)) + boost, 4)
        hits.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        return hits

    # -- save ------------------------------------------------------------
    def save(
        self,
        content: str,
        title: str | None = None,
        category: str = "notes",
        tags: list[str] | None = None,
        source: str = "",
        agent: str = "default",
        links: list[str] | None = None,
        entities: list[str] | None = None,
        project: str | None = None,
        user: str = "",
        importance: int | None = None,
        pinned: bool = False,
        allow_duplicate: bool = False,
    ) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)

        findings = redact.scan(content)
        if config.redact_on_save and findings:
            content, findings = redact.redact(content)

        # Embeddings are the slowest step: compute them BEFORE taking the
        # process-wide lock. The dedup probe runs under the lock so concurrent
        # saves see each other's writes.
        qvec = None
        if config.safe_save and not allow_duplicate and content.strip():
            try:
                qvec = self.embedder.embed_query(content)
            except Exception as exc:
                _log.warning("dedup probe embedding failed: %s", exc)
        chunks = chunk_text(content, config.chunk_size, config.chunk_overlap)
        vectors = self.embedder.embed_documents(chunks) if chunks else []

        ents = graph.extract_entities(content, entities)
        imp = self._importance(content, category, ents, importance)
        with self._lock:
            if qvec is not None:
                try:
                    hits = store.search(qvec, limit=1)
                    if hits and hits[0].get("score", 0) >= config.dedup_threshold:
                        existing = vault.find_note(project, hits[0]["note_id"])
                        if existing:
                            result = existing.to_dict()
                            result.update(
                                duplicate=True,
                                similarity=hits[0]["score"],
                                chunks=0,
                                pii_findings=findings,
                            )
                            return result
                except Exception as exc:
                    _log.warning("dedup probe search failed: %s", exc)
            note = vault.write_note(
                project=project,
                content=content,
                title=title,
                category=category,
                tags=tags,
                source=source,
                agent=agent,
                links=links,
                entities=ents,
                user=user,
                importance=imp,
                pinned=pinned,
            )
            if not chunks:
                chunks = [note.title]
                vectors = self.embedder.embed_documents(chunks)
            store.upsert_note(note, vectors, chunks)
            self._invalidate_corpus(project)
        self._metrics["save"] += 1
        result = note.to_dict()
        result.update(duplicate=False, chunks=len(chunks), pii_findings=findings)
        return result

    # -- search ----------------------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 8,
        category: str | None = None,
        agent: str | None = None,
        tag: str | None = None,
        project: str | None = None,
        user: str | None = None,
        include_archived: bool = False,
        hybrid_search: bool | None = None,
        searched_by: str = "default",
        log: bool = True,
    ) -> list[dict]:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        self._metrics["search"] += 1
        use_hybrid = config.hybrid_search if hybrid_search is None else hybrid_search

        notes_by_id, bm25_idx = self._corpus(project)

        def _ok(note) -> bool:
            # Activity notes (old search logs etc.) never surface unless asked for.
            if note.category == "activity" and category != "activity":
                return False
            if category and note.category != category:
                return False
            if agent and note.agent != agent:
                return False
            if user is not None and note.user != user:
                return False
            if note.archived and not include_archived:
                return False
            return True

        # dense retrieval (collapse to best score per note)
        qvec = self.embedder.embed_query(query)
        overfetch = max(limit * config.search_overfetch, 20)
        dense_best: dict[str, float] = {}
        for h in store.search(qvec, limit=overfetch):
            nid = h.get("note_id")
            if nid in notes_by_id:
                dense_best[nid] = max(dense_best.get(nid, -1.0), float(h.get("score", 0)))
        dense_ids = [nid for nid, _ in sorted(dense_best.items(), key=lambda x: x[1], reverse=True)]

        if use_hybrid:
            sparse_ids = [nid for nid, _ in hybrid.bm25_rank_indexed(query, bm25_idx)]
            fused = hybrid.rrf_fuse(dense_ids, sparse_ids, k=config.rrf_k)
            ranked = [(nid, sc) for nid, sc in fused]
        else:
            ranked = [(nid, dense_best[nid]) for nid in dense_ids]

        # Normalize relevance to [0,1] so the usefulness/access/recency boosts
        # in _final_rank don't dwarf it (raw RRF scores max out around 0.033).
        top = max((sc for _, sc in ranked), default=0.0)
        if top > 0:
            ranked = [(nid, sc / top) for nid, sc in ranked]

        allowed_tags = set(ontology.descendants(tag)) if tag else None
        hits: list[dict] = []
        for nid, score in ranked:
            note = notes_by_id.get(nid)
            if not note or not _ok(note):
                continue
            if allowed_tags is not None and not ({t.lower() for t in note.tags} & allowed_tags):
                continue
            hits.append(self._hit(note, score))

        hits = self._final_rank(hits)[:limit]

        # Search logs go to a plain JSONL file (reserved "_" path, never
        # indexed/embedded) — logging them as notes fed queries back into
        # future retrieval.
        if log and config.log_searches and query.strip():
            try:
                rec = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "agent": searched_by,
                    "query": query,
                    "results": len(hits),
                }
                path = vault.project_dir(project) / "_search_log.jsonl"
                with self._lock:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except Exception as exc:
                _log.warning("search log append failed: %s", exc)
        return hits

    def recall(
        self,
        query: str,
        project: str | None = None,
        token_budget: int | None = None,
        user: str | None = None,
        agent: str | None = None,
        searched_by: str = "default",
    ) -> dict:
        project = vault.sanitize_project(project)
        budget = token_budget or config.recall_token_budget
        q = query.lower()
        self._metrics["recall"] += 1

        memories = self.search(
            query, limit=6, project=project, user=user, searched_by=searched_by, log=False
        )
        procedures = self.search(query, limit=4, category="procedure", project=project, log=False)
        soul_text = soul.merged_soul(project, agent).strip()
        core_blocks = blocks.list_blocks(project, agent)
        prefs = preferences.merged_prefs(project, agent)
        directive_notes = self.directives(project)

        ents = graph.entity_list(project)
        ql_tokens = set(q.replace("?", " ").split())
        # Exact-token match plus a substring pass so multi-word entities
        # ("acme corp") surface too.
        matched_entities = [
            e
            for e in ents
            if e["entity"].lower() in ql_tokens
            or (len(e["entity"]) >= 3 and e["entity"].lower() in q)
        ][:5]
        rel_facts: list[dict] = []
        for e in matched_entities:
            rel_facts.extend(facts.current_facts(project, subject=e["entity"]))

        wants_procedure = any(cue in q for cue in _PROCEDURE_CUES)
        order = [
            "soul",
            "directives",
            "blocks",
            "preferences",
            "facts",
            "memories",
            "procedures",
            "entities",
        ]
        if wants_procedure:
            order = [
                "soul",
                "directives",
                "blocks",
                "preferences",
                "procedures",
                "facts",
                "memories",
                "entities",
            ]
        # Always-applied, high-value layers are protected from being dropped.
        guaranteed = {"soul", "directives", "facts"}

        char_budget = budget * 4
        parts: list[str] = []
        used = 0
        included: list[str] = []
        dropped: list[str] = []

        def _fact_line(f: dict) -> str:
            who = f.get("agent", "default")
            suffix = f" [{who}]" if who and who != "default" else ""
            return f"- {f['subject']} {f['predicate']} {f['value']}{suffix}"

        sections = {
            "soul": ("SOUL", soul.soul_for_recall(soul_text, 800) if soul_text else ""),
            "directives": (
                "Directives (always apply)",
                "\n".join(f"- {d['title']}: {d['text'][:160]}" for d in directive_notes),
            ),
            "blocks": (
                "Memory blocks",
                "\n".join(f"### {k}\n{v[:400]}" for k, v in core_blocks.items()),
            ),
            "preferences": ("Preferences", "\n".join(f"- {k}: {v}" for k, v in prefs.items())),
            "facts": ("Current facts", "\n".join(_fact_line(f) for f in rel_facts)),
            "memories": (
                "Relevant memories",
                "\n".join(
                    f"- ({h.get('final_score')}) {h.get('title')}: {h.get('text', '')[:200]}"
                    for h in memories
                ),
            ),
            "procedures": (
                "Procedures",
                "\n".join(f"- {h.get('title')}: {h.get('text', '')[:200]}" for h in procedures),
            ),
            "entities": ("Related entities", ", ".join(e["entity"] for e in matched_entities)),
        }
        for key in order:
            label, text = sections[key]
            if not text:
                continue
            block = f"## {label}\n{text}\n"
            if key in guaranteed or used + len(block) <= char_budget:
                parts.append(block)
                used += len(block)
                included.append(key)
            else:
                dropped.append(key)

        return {
            "project": project,
            "query": query,
            "priority_order": order,
            "included_layers": included,
            "dropped_layers": dropped,
            "soul": soul_text,
            "directives": directive_notes,
            "blocks": core_blocks,
            "preferences": prefs,
            "facts": rel_facts,
            "memories": memories,
            "procedures": procedures,
            "entities": matched_entities,
            "context": "\n".join(parts).strip(),
            "approx_tokens": used // 4,
        }

    # -- relationships / graph ------------------------------------------
    def related(self, note_id: str, project: str | None = None, limit: int = 8) -> list[dict]:
        project = vault.sanitize_project(project)
        base = vault.find_note(project, note_id)
        if not base:
            return []
        store = self._get_store(project)
        out: dict[str, dict] = {}
        for nid in graph.notes_sharing_entities(project, note_id):
            n = vault.find_note(project, nid)
            if n:
                out[nid] = {"note_id": nid, "title": n.title, "reason": "shared-entities"}
        try:
            qvec = self.embedder.embed_query(base.content or base.title)
            for h in store.search(qvec, limit=limit + 5):
                nid = h.get("note_id")
                if nid and nid != note_id and nid not in out:
                    out[nid] = {
                        "note_id": nid,
                        "title": h.get("title"),
                        "reason": "semantic",
                        "score": h.get("score"),
                    }
        except Exception:
            pass
        return list(out.values())[:limit]

    def entities(self, project: str | None = None) -> list[dict]:
        return graph.entity_list(vault.sanitize_project(project))

    def entity_neighbors(self, entity: str, project: str | None = None) -> list[dict]:
        return graph.neighbors(vault.sanitize_project(project), entity)

    def entity_multihop(
        self, entity: str, depth: int = 2, project: str | None = None
    ) -> list[dict]:
        return graph.multihop(vault.sanitize_project(project), entity, depth)

    def communities(self, project: str | None = None) -> list[dict]:
        return graph.communities(vault.sanitize_project(project))

    def graph_data(
        self, project: str | None = None, mode: str = "entities", limit: int = 400
    ) -> dict:
        """Nodes + edges for a force-directed dashboard graph.

        mode="entities": knowledge graph (entities as nodes, co-occurrence edges,
        colored by community). mode="notes": Obsidian-style (notes as nodes, edges
        from explicit links + shared entities)."""
        project = vault.sanitize_project(project)
        if mode == "notes":
            notes = [
                n
                for n, _ in vault.iter_notes(project)
                if not n.archived and n.category != "activity"
            ][:limit]
            ids = {n.id for n in notes}
            nodes = [
                {
                    "id": n.id,
                    "label": n.title,
                    "group": n.category,
                    "val": 1 + max(int(n.importance or 1), 1) + min(int(n.access_count or 0), 5),
                    "category": n.category,
                    "project": project,
                }
                for n in notes
            ]
            edge_set: set[frozenset] = set()
            edges: list[dict] = []

            def _add_edge(a: str, b: str, kind: str):
                if a == b or a not in ids or b not in ids:
                    return
                key = frozenset({a, b})
                if key in edge_set:
                    return
                edge_set.add(key)
                edges.append({"source": a, "target": b, "kind": kind})

            for n in notes:
                for link in n.links or []:
                    _add_edge(n.id, link, "link")
            # bridge notes that share an entity (capped per entity)
            by_entity: dict[str, list[str]] = {}
            for n in notes:
                for e in n.entities or []:
                    by_entity.setdefault(resolve.canonical(e).lower(), []).append(n.id)
            for members in by_entity.values():
                members = members[:8]
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        _add_edge(members[i], members[j], "shared-entity")
                        if len(edges) > limit * 6:
                            break
            return {"mode": "notes", "project": project, "nodes": nodes, "edges": edges}

        # entities mode
        g = graph.build_graph(project)
        comm_of: dict[str, int] = {}
        for c in graph.communities(project):
            for m in c["members"]:
                comm_of[m] = c["id"]
        entities = sorted(g["entities"].items(), key=lambda x: x[1], reverse=True)[:limit]
        keep = {e for e, _ in entities}
        nodes = [
            {
                "id": e,
                "label": e,
                "group": comm_of.get(e, 0),
                "val": 2 + min(c, 12),
                "mentions": c,
                "project": project,
            }
            for e, c in entities
        ]
        edges = []
        for key, w in g["edges"].items():
            a, b = key.split("|||")
            if a in keep and b in keep:
                edges.append({"source": a, "target": b, "weight": w, "kind": "co-occurrence"})
        return {"mode": "entities", "project": project, "nodes": nodes, "edges": edges}

    def entity_notes(self, entity: str, project: str | None = None) -> list[dict]:
        project = vault.sanitize_project(project)
        out = []
        for nid in graph.notes_for_entity(project, entity):
            n = vault.find_note(project, nid)
            if n:
                out.append({"note_id": nid, "title": n.title})
        return out

    def set_alias(self, alias: str, canonical: str) -> dict:
        return resolve.set_alias(alias, canonical)

    # -- facts (bi-temporal) --------------------------------------------
    def add_fact(
        self,
        subject: str,
        value: str,
        predicate: str = "is",
        source: str = "",
        agent: str = "default",
        project: str | None = None,
    ) -> dict:
        self._metrics["fact"] += 1
        return facts.add_fact(
            vault.sanitize_project(project), subject, value, predicate, source=source, agent=agent
        )

    def facts(self, subject: str | None = None, project: str | None = None) -> list[dict]:
        return facts.current_facts(vault.sanitize_project(project), subject=subject)

    def fact_history(self, subject: str, project: str | None = None) -> list[dict]:
        return facts.history(vault.sanitize_project(project), subject)

    # -- self / blocks / preferences / ontology -------------------------
    def get_soul(self, project: str | None = None, agent: str | None = None) -> str:
        return soul.get_soul(vault.sanitize_project(project), agent)

    def set_soul(self, text: str, project: str | None = None, agent: str | None = None) -> str:
        return soul.set_soul(vault.sanitize_project(project), text, agent)

    def learn_principle(
        self, principle: str, project: str | None = None, agent: str | None = None
    ) -> str:
        return soul.append_principle(vault.sanitize_project(project), principle, agent)

    def get_block(self, name: str, project: str | None = None, agent: str | None = None) -> str:
        return blocks.get_block(vault.sanitize_project(project), name, agent)

    def set_block(
        self, name: str, text: str, project: str | None = None, agent: str | None = None
    ) -> str:
        return blocks.set_block(vault.sanitize_project(project), name, text, agent)

    def append_block(
        self, name: str, text: str, project: str | None = None, agent: str | None = None
    ) -> str:
        return blocks.append_block(vault.sanitize_project(project), name, text, agent)

    def list_blocks(self, project: str | None = None, agent: str | None = None) -> dict:
        return blocks.list_blocks(vault.sanitize_project(project), agent)

    def get_preferences(self, project: str | None = None, agent: str | None = None) -> dict:
        return preferences.all_prefs(vault.sanitize_project(project), agent)

    def set_preference(
        self, key: str, value: str, project: str | None = None, agent: str | None = None
    ) -> dict:
        return preferences.set_pref(vault.sanitize_project(project), key, value, agent)

    def set_ontology(self, tag: str, parent: str) -> dict:
        return ontology.set_parent(tag, parent)

    def get_ontology(self) -> dict:
        return ontology.taxonomy()

    # -- get / recent / activity / feedback / archive -------------------
    def get(self, note_id: str, project: str | None = None, track: bool = True) -> dict | None:
        project = vault.sanitize_project(project)
        note = vault.find_note(project, note_id)
        if not note:
            return None
        if track:
            try:
                with self._lock:
                    note.access_count = int(note.access_count or 0) + 1
                    vault.update_note(note)
                    self._invalidate_corpus(project)
                    self._set_payload(
                        project,
                        note.id,
                        {"access_count": note.access_count, "updated": note.updated},
                    )
            except Exception as exc:
                _log.warning("access tracking for note %s failed: %s", note_id, exc)
        return note.to_dict()

    def recent(
        self, n: int = 20, project: str | None = None, include_archived: bool = False
    ) -> list[dict]:
        project = vault.sanitize_project(project)
        return [x.to_dict() for x in vault.recent_notes(project, n, include_archived)]

    def activity(
        self, agent: str | None = None, n: int = 20, project: str | None = None
    ) -> list[dict]:
        project = vault.sanitize_project(project)
        notes = vault.recent_notes(project, 500)
        if agent:
            notes = [x for x in notes if x.agent == agent]
        return [
            {
                "id": x.id,
                "title": x.title,
                "project": x.project,
                "category": x.category,
                "agent": x.agent,
                "updated": x.updated,
                "tags": x.tags,
                "usefulness": x.usefulness,
                "access_count": x.access_count,
                "importance": x.importance,
            }
            for x in notes
        ][:n]

    def feedback(
        self, note_id: str, useful: bool = True, project: str | None = None
    ) -> dict | None:
        project = vault.sanitize_project(project)
        with self._lock:
            note = vault.find_note(project, note_id)
            if not note:
                return None
            note.usefulness = max(0, int(note.usefulness or 0) + (1 if useful else -1))
            vault.update_note(note)
            self._invalidate_corpus(project)
            self._set_payload(
                project, note.id, {"usefulness": note.usefulness, "updated": note.updated}
            )
        return {"id": note.id, "usefulness": note.usefulness}

    def set_archived(self, note_id: str, archived: bool, project: str | None = None) -> dict | None:
        project = vault.sanitize_project(project)
        with self._lock:
            note = vault.find_note(project, note_id)
            if not note:
                return None
            note.archived = archived
            vault.update_note(note)
            self._invalidate_corpus(project)
            self._set_payload(
                project, note.id, {"archived": note.archived, "updated": note.updated}
            )
        return {"id": note.id, "archived": note.archived}

    # -- directives / pinned ("always apply") ---------------------------
    def directives(self, project: str | None = None) -> list[dict]:
        project = vault.sanitize_project(project)
        out = []
        for note, _ in vault.iter_notes(project):
            if note.pinned and not note.archived:
                out.append(
                    {
                        "id": note.id,
                        "title": note.title,
                        "text": (note.content or "")[:400],
                        "category": note.category,
                        "agent": note.agent,
                    }
                )
        out.sort(key=lambda d: d["id"], reverse=True)
        return out

    def set_pinned(self, note_id: str, pinned: bool, project: str | None = None) -> dict | None:
        project = vault.sanitize_project(project)
        with self._lock:
            note = vault.find_note(project, note_id)
            if not note:
                return None
            note.pinned = pinned
            vault.update_note(note)
            self._invalidate_corpus(project)
            self._set_payload(project, note.id, {"pinned": note.pinned, "updated": note.updated})
        return {"id": note.id, "pinned": note.pinned}

    def add_directive(self, text: str, project: str | None = None, agent: str = "default") -> dict:
        """Save an always-applied directive (a pinned note surfaced in every recall)."""
        return self.save(
            content=text,
            title=f"directive: {text[:50]}",
            category="directive",
            tags=["directive"],
            agent=agent,
            project=project,
            importance=5,
            pinned=True,
            allow_duplicate=True,
        )

    def ingest(
        self,
        text: str,
        title: str | None = None,
        source: str = "conversation",
        tags: list[str] | None = None,
        agent: str = "default",
        project: str | None = None,
    ) -> dict:
        project = vault.sanitize_project(project)
        body = maybe_summarize(text)
        self._metrics["ingest"] += 1
        return self.save(
            content=body,
            title=title or f"conversation {body.strip()[:50]}",
            category="conversations",
            tags=(tags or []) + ["episode", "ingested"],
            source=source,
            agent=agent,
            project=project,
        )

    def ingest_file(self, path, project: str | None = None, agent: str = "default") -> dict:
        from pathlib import Path

        p = Path(path)
        if not p.exists() or not p.is_file():
            return {"error": "not a file", "path": str(path)}
        if p.suffix.lower() not in _TEXT_EXTS:
            return {"error": f"unsupported type {p.suffix}", "path": str(path)}
        if p.stat().st_size > config.ingest_max_bytes:
            return {
                "error": f"file exceeds {config.ingest_max_bytes} bytes",
                "path": str(path),
            }
        text = p.read_text(encoding="utf-8", errors="replace")
        return self.save(
            content=text,
            title=p.name,
            category="knowledge",
            tags=["file"],
            source=f"file:{p.name}",
            agent=agent,
            project=project,
        )

    def ingest_dir(self, path, project: str | None = None, agent: str = "default") -> list[dict]:
        from pathlib import Path

        base = Path(path)
        out = []
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if any(part in _INGEST_IGNORE for part in f.parts):
                    continue
                if f.is_file() and f.suffix.lower() in _TEXT_EXTS:
                    out.append(self.ingest_file(f, project=project, agent=agent))
        return out

    # -- maintenance: consolidate / dream / tick / sleep ----------------
    def consolidate(self, project: str | None = None, threshold: float | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        thr = threshold if threshold is not None else config.dedup_threshold
        notes = vault.recent_notes(project, 5000)
        removed = 0
        merged_into: dict[str, list[str]] = {}
        alive = {n.id for n in notes}
        for keeper in notes:
            if keeper.id not in alive or keeper.category == "activity" or keeper.archived:
                continue
            qvec = self.embedder.embed_query(keeper.content or keeper.title)
            for hit in store.search(qvec, limit=10):
                hid = hit.get("note_id")
                if hid == keeper.id or hid not in alive or hit.get("score", 0) < thr:
                    continue
                dup = vault.find_note(project, hid)
                if not dup or dup.category == "activity" or dup.archived:
                    continue
                keeper.tags = sorted(set(keeper.tags) | set(dup.tags))
                keeper.links = sorted(set(keeper.links) | set(dup.links))
                # The vault is the durability layer: never delete content here.
                # Archive the duplicate and mark where it was merged.
                dup.archived = True
                dup.tags = sorted(set(dup.tags) | {f"merged-into:{keeper.id}"})
                vault.update_note(dup)
                self._set_payload(project, dup.id, {"tags": dup.tags, "updated": dup.updated})
                alive.discard(hid)
                removed += 1
                merged_into.setdefault(keeper.id, []).append(hid)
            if keeper.id in merged_into:
                vault.update_note(keeper)
                self._set_payload(
                    project, keeper.id, {"tags": keeper.tags, "updated": keeper.updated}
                )
        if removed:
            self._invalidate_corpus(project)
        return {"project": project, "removed": removed, "merged_into": merged_into}

    def dream(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        consolidated = self.consolidate(project)["removed"]
        notes = [
            n
            for n in vault.recent_notes(project, 5000)
            if n.category not in ("activity",) and "dream-digest" not in n.tags
        ]
        clustered: set[str] = set()
        digests = 0
        relate = config.dream_relate_threshold
        for seed in notes:
            if seed.id in clustered or digests >= config.dream_max_digests:
                continue
            qvec = self.embedder.embed_query(seed.content or seed.title)
            members = [seed.id]
            for hit in store.search(qvec, limit=8):
                hid = hit.get("note_id")
                if (
                    hid
                    and hid != seed.id
                    and hid not in clustered
                    and relate <= hit.get("score", 0) < config.dedup_threshold
                ):
                    m = vault.find_note(project, hid)
                    if m and "dream-digest" not in m.tags and m.category != "activity":
                        members.append(hid)
            if len(members) >= 2:
                member_notes = [vault.find_note(project, m) for m in members]
                member_notes = [m for m in member_notes if m]
                body = "Synthesized from related memories:\n\n" + "\n".join(
                    f"- [[{m.title}]] — {(m.content or '').strip()[:120]}" for m in member_notes
                )
                body = maybe_summarize(body)
                with self._lock:
                    digest = vault.write_note(
                        project=project,
                        content=body,
                        title=f"digest: {seed.title[:50]}",
                        category="knowledge",
                        tags=["dream-digest"],
                        source="dream",
                        agent="brain",
                        links=[m.id for m in member_notes],
                        importance=3,
                    )
                    self._index_note(store, digest)
                    self._invalidate_corpus(project)
                for m in members:
                    clustered.add(m)
                digests += 1
        return {"project": project, "consolidated": consolidated, "digests_created": digests}

    def tick(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        self._get_store(project)
        decayed = 0
        with self._lock:
            for note in vault.recent_notes(project, 5000):
                if note.category == "activity":
                    continue
                if int(note.usefulness or 0) > 0 and int(note.access_count or 0) == 0:
                    note.usefulness = max(0, int(note.usefulness) - config.decay_step)
                    vault.update_note(note)
                    self._set_payload(
                        project, note.id, {"usefulness": note.usefulness, "updated": note.updated}
                    )
                    decayed += 1
            if decayed:
                self._invalidate_corpus(project)
        # Promote-and-close sessions idle past the retention window.
        sessions_closed = 0
        retention = config.session_retention_days
        for s in session.list_sessions(project):
            age = self._age_days(s.get("last_ts") or "")
            if age is not None and age > retention:
                try:
                    self.close_session(project, s["session"])
                    sessions_closed += 1
                except Exception as exc:
                    _log.warning("auto-close of session %r failed: %s", s["session"], exc)
        consolidated = self.consolidate(project)["removed"]
        return {
            "project": project,
            "decayed": decayed,
            "consolidated": consolidated,
            "sessions_closed": sessions_closed,
        }

    def sleep_cycle(self, project: str | None = None) -> dict:
        """A fuller maintenance pass: reflect (dream) + optionally archive stale,
        low-value memories + report remaining issues."""
        project = vault.sanitize_project(project)
        dreamed = self.dream(project)
        archived = 0
        if config.sleep_archive:
            with self._lock:
                for note in vault.recent_notes(project, 5000):
                    if (
                        note.category not in ("activity",)
                        and not note.archived
                        and int(note.access_count or 0) == 0
                        and int(note.importance or 1) <= 1
                        and "dream-digest" not in note.tags
                    ):
                        note.archived = True
                        vault.update_note(note)
                        self._set_payload(
                            project, note.id, {"archived": True, "updated": note.updated}
                        )
                        archived += 1
                if archived:
                    self._invalidate_corpus(project)
        report = self.doctor(project)
        return {
            "project": project,
            "dreamed": dreamed,
            "archived": archived,
            "remaining_issues": report["summary"],
        }

    def heartbeat_all(self) -> dict:
        results = [self.tick(p) for p in vault.list_projects()]
        return {"ticked": len(results), "results": results}

    # -- doctor (memory quality audit) ----------------------------------
    def doctor(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        notes = [n for n in vault.recent_notes(project, 5000) if n.category != "activity"]
        by_id = {n.id: n for n in notes}

        dup_pairs: list[list[str]] = []
        seen_pairs: set[frozenset] = set()
        for n in notes:
            try:
                qvec = self.embedder.embed_query(n.content or n.title)
                for hit in store.search(qvec, limit=4):
                    hid = hit.get("note_id")
                    if (
                        hid
                        and hid != n.id
                        and hid in by_id
                        and hit.get("score", 0) >= config.dedup_threshold
                    ):
                        pair = frozenset({n.id, hid})
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            dup_pairs.append(sorted(pair))
            except Exception:
                pass

        stale = [
            {"id": n.id, "title": n.title}
            for n in notes
            if int(n.access_count or 0) == 0 and int(n.importance or 1) <= 1
        ][:50]

        g = graph.build_graph(project)
        degree: dict[str, int] = {e: 0 for e in g["entities"]}
        for key in g["edges"]:
            a, b = key.split("|||")
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        orphan_entities = sorted(e for e, d in degree.items() if d == 0)

        oversized = [
            name
            for name, txt in blocks.list_blocks(project).items()
            if len(txt) > config.block_char_limit
        ]

        pii = []
        for n in notes:
            f = redact.scan(n.content)
            if f:
                pii.append({"id": n.id, "title": n.title, "types": sorted({x["type"] for x in f})})

        contras = facts.contradictions(project)

        summary = {
            "duplicate_pairs": len(dup_pairs),
            "stale": len(stale),
            "orphan_entities": len(orphan_entities),
            "oversized_blocks": len(oversized),
            "pii_notes": len(pii),
            "fact_contradictions": len(contras),
        }
        return {
            "project": project,
            "summary": summary,
            "duplicate_pairs": dup_pairs[:50],
            "stale": stale,
            "orphan_entities": orphan_entities[:50],
            "oversized_blocks": oversized,
            "pii_notes": pii[:50],
            "fact_contradictions": contras,
        }

    # -- export / import -------------------------------------------------
    def export(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        base = vault.project_dir(project)
        # Per-agent blocks live in _blocks/<agent>/<name>.md; per-agent prefs
        # in _prefs/<agent>.md. Enumerate them from disk (setters exist for
        # import, but no listing API).
        agent_blocks: dict[str, dict[str, str]] = {}
        bdir = base / "_blocks"
        if bdir.exists():
            for sub in sorted(p for p in bdir.iterdir() if p.is_dir()):
                agent_blocks[sub.name] = {
                    f.stem: f.read_text(encoding="utf-8") for f in sorted(sub.glob("*.md"))
                }
        pdir = base / "_prefs"
        pref_agents = sorted(p.stem for p in pdir.glob("*.md")) if pdir.exists() else []
        return {
            "version": "0.0.1.6",
            "project": project,
            "notes": [n.to_dict() for n, _ in vault.iter_notes(project)],
            "soul": soul.get_soul(project),
            "agent_souls": soul.list_agent_souls(project),
            "blocks": blocks.list_blocks(project),
            "agent_blocks": agent_blocks,
            "preferences": preferences.all_prefs(project),
            "agent_preferences": {a: preferences.all_prefs(project, a) for a in pref_agents},
            "facts": facts.all_facts(project),
            "sessions": session.export_sessions(project),
            "ontology": ontology.taxonomy(),
            "not_included": ["entity aliases (global aliases.json)", "audit.log"],
        }

    def import_bundle(self, bundle: dict, project: str | None = None) -> dict:
        project = vault.sanitize_project(project or bundle.get("project"))
        self._get_store(project)
        n = 0
        with self._lock:
            for nd in bundle.get("notes", []):
                vault.write_note(
                    project=project,
                    content=nd.get("content", ""),
                    title=nd.get("title"),
                    category=nd.get("category", "notes"),
                    tags=nd.get("tags") or [],
                    source=nd.get("source", ""),
                    agent=nd.get("agent", "default"),
                    links=nd.get("links") or [],
                    entities=nd.get("entities") or [],
                    note_id=nd.get("id"),
                    usefulness=int(nd.get("usefulness") or 0),
                    access_count=int(nd.get("access_count") or 0),
                    importance=int(nd.get("importance") or 1),
                    archived=bool(nd.get("archived") or False),
                    pinned=bool(nd.get("pinned") or False),
                    user=nd.get("user", ""),
                )
                n += 1
            if bundle.get("soul"):
                soul.set_soul(project, bundle["soul"])
            for agent_name, text in (bundle.get("agent_souls") or {}).items():
                soul.set_soul(project, text, agent_name)
            for name, text in (bundle.get("blocks") or {}).items():
                blocks.set_block(project, name, text)
            for agent_name, blks in (bundle.get("agent_blocks") or {}).items():
                for name, text in (blks or {}).items():
                    blocks.set_block(project, name, text, agent_name)
            for k, v in (bundle.get("preferences") or {}).items():
                preferences.set_pref(project, k, v)
            for agent_name, prefs in (bundle.get("agent_preferences") or {}).items():
                for k, v in (prefs or {}).items():
                    preferences.set_pref(project, k, v, agent_name)
            if bundle.get("facts"):
                facts._save(project, bundle["facts"])
            session.import_sessions(project, bundle.get("sessions") or {})
            for tag_name, parent in (bundle.get("ontology") or {}).items():
                ontology.set_parent(tag_name, parent)
            self._invalidate_corpus(project)
            self.reindex(project)
        return {"project": project, "imported_notes": n}

    # -- delete / reindex / projects / stats / metrics ------------------
    def delete(self, note_id: str, project: str | None = None) -> bool:
        project = vault.sanitize_project(project)
        with self._lock:
            ok = vault.delete_note(project, note_id)
            if ok:
                self._get_store(project).delete_note(note_id)
                self._invalidate_corpus(project)
            return ok

    def reindex(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        with self._lock:
            store = self._get_store(project)
            store.reset()
            notes = self._reindex_project(project, store)
        return {"project": project, "notes": notes, "vectors": store.count()}

    def projects(self) -> list[dict]:
        out = []
        for p in vault.list_projects():
            store = self._get_store(p)
            out.append(
                {
                    "project": p,
                    "notes": sum(1 for _ in vault.iter_notes(p)),
                    "vectors": store.count(),
                    "entities": len(graph.entity_list(p)),
                }
            )
        return out

    # -- real-time session / checkpoint layer ---------------------------
    def checkpoint(
        self,
        note: str,
        session_id: str = "default",
        agent: str = "default",
        files: list[str] | None = None,
        git_ref: str = "",
        next_step: str = "",
        status: str = "working",
        project: str | None = None,
    ) -> dict:
        self._metrics["checkpoint"] += 1
        return session.add_checkpoint(
            vault.sanitize_project(project),
            note=note,
            session=session_id,
            agent=agent,
            files=files,
            git_ref=git_ref,
            next_step=next_step,
            status=status,
        )

    def resume(self, session_id: str | None = None, project: str | None = None, n: int = 5) -> dict:
        return session.resume(vault.sanitize_project(project), session=session_id, n=n)

    def sessions(self, project: str | None = None) -> list[dict]:
        return session.list_sessions(vault.sanitize_project(project))

    def close_session(self, project: str, session: str) -> dict:
        """Promote a session's checkpoint trail into ONE durable summary note,
        then mark the journal closed (renamed to .jsonl.closed)."""
        from . import session as sessionlog  # the `session` param shadows the module

        project = vault.sanitize_project(project)
        recs = sessionlog.read_checkpoints(project, session)
        if not recs:
            return {"summary_note_id": None, "checkpoints": 0}
        # No LLM: a compact structured digest of the trail (most recent last).
        lines = [
            f"Session '{session}': {len(recs)} checkpoints, "
            f"{recs[0].get('ts', '?')} → {recs[-1].get('ts', '?')}.",
            "",
        ]
        for r in recs[-50:]:
            line = f"- [{r.get('ts', '')}] ({r.get('status', '')}) {r.get('note', '')[:200]}"
            if r.get("next"):
                line += f" | next: {r['next'][:100]}"
            lines.append(line)
        body = "\n".join(lines)[:8000]
        saved = self.save(
            content=body,
            title=f"session summary: {session}",
            category="notes",
            tags=["session-summary"],
            source=f"session:{session}",
            agent=recs[-1].get("agent", "default"),
            project=project,
            allow_duplicate=True,
        )
        sessionlog.close(project, session)
        return {"summary_note_id": saved.get("id"), "checkpoints": len(recs)}

    def metrics(self) -> dict:
        return dict(self._metrics)

    def stats(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        return {
            "project": project,
            "notes": sum(1 for _ in vault.iter_notes(project)),
            "vectors": store.count(),
            "entities": len(graph.entity_list(project)),
            "facts": len(facts.current_facts(project)),
            "embed_model": config.embed_model,
            "embed_dim": self.embedder.dim,
            "hybrid_search": config.hybrid_search,
            "collection": store.collection,
            "qdrant": "server" if config.qdrant_url else "embedded",
            "all_projects": vault.list_projects(),
        }
