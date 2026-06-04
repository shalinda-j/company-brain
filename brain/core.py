"""The Brain: ties the vault (source of truth), the embedder (local CPU), and
the vector store (semantic search) together into one simple interface.

Public operations:
    save     - store a memory (writes Markdown + indexes it)
    search   - semantic search (optionally logs the query as a memory)
    get      - fetch one note in full
    recent   - latest notes
    activity - what each agent has been doing (multi-agent visibility)
    reindex  - rebuild the vector index from the vault (resilience)
    delete   - remove a note from both vault and index
"""
from __future__ import annotations

import threading

from . import vault
from .chunking import chunk_text
from .config import config
from .embeddings import get_embedder
from .store import VectorStore


class Brain:
    def __init__(self):
        config.ensure_dirs()
        self._lock = threading.Lock()
        self.embedder = get_embedder(config.embed_model, config.embed_cache_dir)
        self.store = VectorStore(dim=self.embedder.dim)
        # On startup, make sure everything in the vault is indexed.
        self._reconcile_on_start()

    # -- internal --------------------------------------------------------
    def _index_note(self, note) -> int:
        chunks = chunk_text(note.content, config.chunk_size, config.chunk_overlap)
        if not chunks:
            chunks = [note.title]
        vectors = self.embedder.embed_documents(chunks)
        self.store.upsert_note(note, vectors, chunks)
        return len(chunks)

    def _reconcile_on_start(self) -> None:
        # If the index is empty but the vault has notes, rebuild it.
        try:
            if self.store.count() == 0 and any(True for _ in vault.iter_notes()):
                self.reindex()
        except Exception:
            # Never block startup on reconcile.
            pass

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
    ) -> dict:
        with self._lock:
            note = vault.write_note(
                content=content,
                title=title,
                category=category,
                tags=tags,
                source=source,
                agent=agent,
                links=links,
            )
            n_chunks = self._index_note(note)
        result = note.to_dict()
        result["chunks"] = n_chunks
        return result

    def search(
        self,
        query: str,
        limit: int = 8,
        category: str | None = None,
        agent: str | None = None,
        tag: str | None = None,
        searched_by: str = "default",
    ) -> list[dict]:
        qvec = self.embedder.embed_query(query)
        hits = self.store.search(qvec, limit=limit, category=category, agent=agent, tag=tag)
        # Optionally remember what was searched for.
        if config.log_searches and query.strip():
            try:
                with self._lock:
                    note = vault.write_note(
                        content=f"Query: {query}\nResults: {len(hits)}",
                        title=f"search: {query[:60]}",
                        category="activity",
                        tags=["search"],
                        source="search-log",
                        agent=searched_by,
                    )
                    self._index_note(note)
            except Exception:
                pass
        return hits

    def get(self, note_id: str) -> dict | None:
        note = vault.find_note(note_id)
        return note.to_dict() if note else None

    def recent(self, n: int = 20) -> list[dict]:
        return [note.to_dict() for note in vault.recent_notes(n)]

    def activity(self, agent: str | None = None, n: int = 20) -> list[dict]:
        notes = vault.recent_notes(500)
        if agent:
            notes = [x for x in notes if x.agent == agent]
        items = [
            {
                "id": x.id,
                "title": x.title,
                "category": x.category,
                "agent": x.agent,
                "updated": x.updated,
                "tags": x.tags,
            }
            for x in notes
        ]
        return items[:n]

    def delete(self, note_id: str) -> bool:
        with self._lock:
            ok = vault.delete_note(note_id)
            if ok:
                self.store.delete_note(note_id)
            return ok

    def reindex(self) -> dict:
        with self._lock:
            self.store.reset()
            notes = chunks = 0
            for note, _ in vault.iter_notes():
                self._index_note(note)
                notes += 1
        return {"notes": notes, "vectors": self.store.count()}

    def stats(self) -> dict:
        return {
            "notes": sum(1 for _ in vault.iter_notes()),
            "vectors": self.store.count(),
            "embed_model": config.embed_model,
            "embed_dim": self.embedder.dim,
            "collection": config.qdrant_collection,
            "qdrant": "server" if config.qdrant_url else "embedded",
        }
