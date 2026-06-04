"""The Brain v2: shared embedder + per-project vector stores + Markdown vault.

New in v2:
- Projects: every operation is scoped to a project (own vault + collection).
- Safe save: near-duplicate detection so the same memory is not stored twice.
- Feedback: mark a memory useful; search blends usefulness into ranking.
- Consolidation: merge near-duplicate memories (self-optimization).
- Ingest: capture conversation text (optionally summarized) as memories.
- Resilience: a vector-dimension mismatch auto-rebuilds and re-indexes the vault.
"""

from __future__ import annotations

import math
import threading

from . import vault
from .chunking import chunk_text
from .config import config
from .embeddings import get_embedder
from .store import VectorStore
from .summarize import maybe_summarize


class Brain:
    def __init__(self):
        config.ensure_dirs()
        self._lock = threading.RLock()
        self.embedder = get_embedder(config.embed_model, config.embed_cache_dir)
        self._stores: dict[str, VectorStore] = {}
        # Reconcile every existing project on startup.
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
                # Fresh or rebuilt collection with notes in the vault -> reindex.
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

    # -- public ----------------------------------------------------------
    def save(
        self,
        content: str,
        title: str | None = None,
        category: str = "notes",
        tags: list[str] | None = None,
        source: str = "",
        agent: str = "default",
        links: list[str] | None = None,
        project: str | None = None,
        allow_duplicate: bool = False,
    ) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)

        # Safe-learning guardrail: skip storing a near-identical memory.
        if config.safe_save and not allow_duplicate and content.strip():
            try:
                qvec = self.embedder.embed_query(content)
                hits = store.search(qvec, limit=1)
                if hits and hits[0].get("score", 0) >= config.dedup_threshold:
                    existing = vault.find_note(project, hits[0]["note_id"])
                    if existing:
                        result = existing.to_dict()
                        result["duplicate"] = True
                        result["similarity"] = hits[0]["score"]
                        result["chunks"] = 0
                        return result
            except Exception:
                pass

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
            )
            n_chunks = self._index_note(store, note)
        result = note.to_dict()
        result["duplicate"] = False
        result["chunks"] = n_chunks
        return result

    def search(
        self,
        query: str,
        limit: int = 8,
        category: str | None = None,
        agent: str | None = None,
        tag: str | None = None,
        project: str | None = None,
        searched_by: str = "default",
    ) -> list[dict]:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        qvec = self.embedder.embed_query(query)
        overfetch = max(limit, limit * config.search_overfetch)
        raw = store.search(qvec, limit=overfetch, category=category, agent=agent, tag=tag)
        hits = self._rerank(raw)[:limit]

        if config.log_searches and query.strip():
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

    def _rerank(self, hits: list[dict]) -> list[dict]:
        """Blend semantic score with a bounded usefulness boost."""
        w = config.feedback_weight
        for h in hits:
            u = int(h.get("usefulness", 0) or 0)
            boost = w * (math.log1p(max(u, 0)) / math.log1p(10))  # saturates near u=10
            h["final_score"] = round(float(h.get("score", 0)) + boost, 4)
        hits.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        return hits

    def get(self, note_id: str, project: str | None = None) -> dict | None:
        project = vault.sanitize_project(project)
        note = vault.find_note(project, note_id)
        return note.to_dict() if note else None

    def recent(self, n: int = 20, project: str | None = None) -> list[dict]:
        project = vault.sanitize_project(project)
        return [note.to_dict() for note in vault.recent_notes(project, n)]

    def activity(
        self, agent: str | None = None, n: int = 20, project: str | None = None
    ) -> list[dict]:
        project = vault.sanitize_project(project)
        notes = vault.recent_notes(project, 500)
        if agent:
            notes = [x for x in notes if x.agent == agent]
        items = [
            {
                "id": x.id,
                "title": x.title,
                "project": x.project,
                "category": x.category,
                "agent": x.agent,
                "updated": x.updated,
                "tags": x.tags,
                "usefulness": x.usefulness,
            }
            for x in notes
        ]
        return items[:n]

    def feedback(
        self, note_id: str, useful: bool = True, project: str | None = None
    ) -> dict | None:
        """Adjust a memory's usefulness (used by search re-ranking)."""
        project = vault.sanitize_project(project)
        with self._lock:
            note = vault.find_note(project, note_id)
            if not note:
                return None
            note.usefulness = max(0, int(note.usefulness or 0) + (1 if useful else -1))
            vault.update_note(note)
            self._index_note(self._get_store(project), note)
        return {"id": note.id, "usefulness": note.usefulness}

    def ingest(
        self,
        text: str,
        title: str | None = None,
        source: str = "conversation",
        tags: list[str] | None = None,
        agent: str = "default",
        project: str | None = None,
    ) -> dict:
        """Capture a chunk of conversation/text as a memory (optionally summarized)."""
        project = vault.sanitize_project(project)
        body = maybe_summarize(text)
        return self.save(
            content=body,
            title=title or f"conversation {body.strip()[:50]}",
            category="conversations",
            tags=(tags or []) + ["ingested"],
            source=source,
            agent=agent,
            project=project,
        )

    def consolidate(self, project: str | None = None, threshold: float | None = None) -> dict:
        """Self-optimization: merge near-duplicate memories within a project.

        Processes newest-first; for each surviving note, removes older notes whose
        similarity exceeds the threshold, folding their tags/links into the keeper.
        """
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        thr = threshold if threshold is not None else config.dedup_threshold
        notes = vault.recent_notes(project, 5000)
        removed = 0
        merged_into: dict[str, list[str]] = {}
        alive_ids = {n.id for n in notes}
        for keeper in notes:
            if keeper.id not in alive_ids:
                continue
            if keeper.category == "activity":
                continue
            qvec = self.embedder.embed_query(keeper.content or keeper.title)
            similar = store.search(qvec, limit=10)
            for hit in similar:
                hid = hit.get("note_id")
                if hid == keeper.id or hid not in alive_ids:
                    continue
                if hit.get("score", 0) < thr:
                    continue
                dup = vault.find_note(project, hid)
                if not dup or dup.category == "activity":
                    continue
                # Fold tags/links into the keeper, then delete the duplicate.
                keeper.tags = sorted(set(keeper.tags) | set(dup.tags))
                keeper.links = sorted(set(keeper.links) | set(dup.links))
                vault.delete_note(project, hid)
                store.delete_note(hid)
                alive_ids.discard(hid)
                removed += 1
                merged_into.setdefault(keeper.id, []).append(hid)
            if keeper.id in merged_into:
                vault.update_note(keeper)
                self._index_note(store, keeper)
        return {"project": project, "removed": removed, "merged_into": merged_into}

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
                }
            )
        return out

    def stats(self, project: str | None = None) -> dict:
        project = vault.sanitize_project(project)
        store = self._get_store(project)
        return {
            "project": project,
            "notes": sum(1 for _ in vault.iter_notes(project)),
            "vectors": store.count(),
            "embed_model": config.embed_model,
            "embed_dim": self.embedder.dim,
            "collection": store.collection,
            "qdrant": "server" if config.qdrant_url else "embedded",
            "all_projects": vault.list_projects(),
        }
