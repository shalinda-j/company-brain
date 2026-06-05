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

import math
import threading
from collections import Counter

from . import blocks, facts, graph, hybrid, ontology, preferences, redact, resolve, soul, vault
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
                except Exception:
                    pass
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
        }

    def _final_rank(self, hits: list[dict]) -> list[dict]:
        wu, wa = config.feedback_weight, config.access_weight
        for h in hits:
            boost = wu * (math.log1p(max(h.get("usefulness", 0), 0)) / math.log1p(10))
            boost += wa * (math.log1p(max(h.get("access_count", 0), 0)) / math.log1p(10))
            boost += 0.05 * (max(h.get("importance", 1), 1) - 1)
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
        allow_duplicate: bool = False,
    ) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)

        findings = redact.scan(content)
        if config.redact_on_save and findings:
            content, findings = redact.redact(content)

        if config.safe_save and not allow_duplicate and content.strip():
            try:
                qvec = self.embedder.embed_query(content)
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
            except Exception:
                pass

        ents = graph.extract_entities(content, entities)
        imp = self._importance(content, category, ents, importance)
        with self._lock:
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
            )
            n_chunks = self._index_note(store, note)
        self._metrics["save"] += 1
        result = note.to_dict()
        result.update(duplicate=False, chunks=n_chunks, pii_findings=findings)
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

        notes_by_id = {n.id: n for n, _ in vault.iter_notes(project)}

        def _ok(note) -> bool:
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
            docs = [(n.id, f"{n.title}\n{n.content}") for n in notes_by_id.values() if _ok(n)]
            sparse_ids = [nid for nid, _ in hybrid.bm25_rank(query, docs)]
            fused = hybrid.rrf_fuse(dense_ids, sparse_ids, k=config.rrf_k)
            ranked = [(nid, sc) for nid, sc in fused]
        else:
            ranked = [(nid, dense_best[nid]) for nid in dense_ids]

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

        if log and config.log_searches and query.strip():
            try:
                with self._lock:
                    note = vault.write_note(
                        project=project,
                        content=f"Query: {query}\nResults: {len(hits)}",
                        title=f"search: {query[:60]}",
                        category="activity",
                        tags=["search"],
                        source="search-log",
                        agent=searched_by,
                    )
                    self._index_note(store, note)
            except Exception:
                pass
        return hits

    def recall(
        self,
        query: str,
        project: str | None = None,
        token_budget: int | None = None,
        user: str | None = None,
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
        soul_text = soul.get_soul(project).strip()
        core_blocks = blocks.list_blocks(project)
        prefs = preferences.all_prefs(project)

        ents = graph.entity_list(project)
        ql_tokens = set(q.replace("?", " ").split())
        matched_entities = [e for e in ents if e["entity"].lower() in ql_tokens][:5]
        rel_facts: list[dict] = []
        for e in matched_entities:
            rel_facts.extend(facts.current_facts(project, subject=e["entity"]))

        wants_procedure = any(cue in q for cue in _PROCEDURE_CUES)
        order = ["soul", "blocks", "preferences", "facts", "memories", "procedures", "entities"]
        if wants_procedure:
            order = ["soul", "blocks", "preferences", "procedures", "facts", "memories", "entities"]

        char_budget = budget * 4
        parts: list[str] = []
        used = 0

        def add(label: str, text: str):
            nonlocal used
            block = f"## {label}\n{text}\n"
            if text and used + len(block) <= char_budget:
                parts.append(block)
                used += len(block)

        sections = {
            "soul": ("SOUL", soul_text[:800] if soul_text else ""),
            "blocks": (
                "Memory blocks",
                "\n".join(f"### {k}\n{v[:400]}" for k, v in core_blocks.items()),
            ),
            "preferences": ("Preferences", "\n".join(f"- {k}: {v}" for k, v in prefs.items())),
            "facts": (
                "Current facts",
                "\n".join(f"- {f['subject']} {f['predicate']} {f['value']}" for f in rel_facts),
            ),
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
            add(label, text)

        return {
            "project": project,
            "query": query,
            "priority_order": order,
            "soul": soul_text,
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
    def get_soul(self, project: str | None = None) -> str:
        return soul.get_soul(vault.sanitize_project(project))

    def set_soul(self, text: str, project: str | None = None) -> str:
        return soul.set_soul(vault.sanitize_project(project), text)

    def learn_principle(self, principle: str, project: str | None = None) -> str:
        return soul.append_principle(vault.sanitize_project(project), principle)

    def get_block(self, name: str, project: str | None = None) -> str:
        return blocks.get_block(vault.sanitize_project(project), name)

    def set_block(self, name: str, text: str, project: str | None = None) -> str:
        return blocks.set_block(vault.sanitize_project(project), name, text)

    def append_block(self, name: str, text: str, project: str | None = None) -> str:
        return blocks.append_block(vault.sanitize_project(project), name, text)

    def list_blocks(self, project: str | None = None) -> dict:
        return blocks.list_blocks(vault.sanitize_project(project))

    def get_preferences(self, project: str | None = None) -> dict:
        return preferences.all_prefs(vault.sanitize_project(project))

    def set_preference(self, key: str, value: str, project: str | None = None) -> dict:
        return preferences.set_pref(vault.sanitize_project(project), key, value)

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
                    self._index_note(self._get_store(project), note)
            except Exception:
                pass
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
            self._index_note(self._get_store(project), note)
        return {"id": note.id, "usefulness": note.usefulness}

    def set_archived(self, note_id: str, archived: bool, project: str | None = None) -> dict | None:
        project = vault.sanitize_project(project)
        with self._lock:
            note = vault.find_note(project, note_id)
            if not note:
                return None
            note.archived = archived
            vault.update_note(note)
            self._index_note(self._get_store(project), note)
        return {"id": note.id, "archived": note.archived}

    # -- ingest ----------------------------------------------------------
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
            if keeper.id not in alive or keeper.category == "activity":
                continue
            qvec = self.embedder.embed_query(keeper.content or keeper.title)
            for hit in store.search(qvec, limit=10):
                hid = hit.get("note_id")
                if hid == keeper.id or hid not in alive or hit.get("score", 0) < thr:
                    continue
                dup = vault.find_note(project, hid)
                if not dup or dup.category == "activity":
                    continue
                keeper.tags = sorted(set(keeper.tags) | set(dup.tags))
                keeper.links = sorted(set(keeper.links) | set(dup.links))
                vault.delete_note(project, hid)
                store.delete_note(hid)
                alive.discard(hid)
                removed += 1
                merged_into.setdefault(keeper.id, []).append(hid)
            if keeper.id in merged_into:
                vault.update_note(keeper)
                self._index_note(store, keeper)
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
                for m in members:
                    clustered.add(m)
                digests += 1
        return {"project": project, "consolidated": consolidated, "digests_created": digests}

    def tick(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        decayed = 0
        with self._lock:
            for note in vault.recent_notes(project, 5000):
                if note.category == "activity":
                    continue
                if int(note.usefulness or 0) > 0 and int(note.access_count or 0) == 0:
                    note.usefulness = max(0, int(note.usefulness) - config.decay_step)
                    vault.update_note(note)
                    self._index_note(store, note)
                    decayed += 1
        consolidated = self.consolidate(project)["removed"]
        return {"project": project, "decayed": decayed, "consolidated": consolidated}

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
                        self._index_note(self._get_store(project), note)
                        archived += 1
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
        return {
            "version": "0.0.1.3",
            "project": project,
            "notes": [n.to_dict() for n, _ in vault.iter_notes(project)],
            "soul": soul.get_soul(project),
            "blocks": blocks.list_blocks(project),
            "preferences": preferences.all_prefs(project),
            "facts": facts.all_facts(project),
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
                    user=nd.get("user", ""),
                )
                n += 1
            if bundle.get("soul"):
                soul.set_soul(project, bundle["soul"])
            for name, text in (bundle.get("blocks") or {}).items():
                blocks.set_block(project, name, text)
            for k, v in (bundle.get("preferences") or {}).items():
                preferences.set_pref(project, k, v)
            if bundle.get("facts"):
                facts._save(project, bundle["facts"])
            self.reindex(project)
        return {"project": project, "imported_notes": n}

    # -- delete / reindex / projects / stats / metrics ------------------
    def delete(self, note_id: str, project: str | None = None) -> bool:
        project = vault.sanitize_project(project)
        with self._lock:
            ok = vault.delete_note(project, note_id)
            if ok:
                self._get_store(project).delete_note(note_id)
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
