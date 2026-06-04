"""Qdrant vector store. v2: one collection per project, automatic recovery from
a vector-dimension mismatch (e.g. after switching embedding model), and a
`usefulness` payload field used for feedback-based re-ranking.
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .config import config

# A single shared client is reused across all per-project collections.
_CLIENT: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _CLIENT
    if _CLIENT is None:
        if config.qdrant_url:
            _CLIENT = QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key)
        else:
            _CLIENT = QdrantClient(path=str(config.qdrant_path))
    return _CLIENT


class VectorStore:
    """Wraps one Qdrant collection for one project."""

    def __init__(self, collection: str, dim: int):
        self.collection = collection
        self.dim = dim
        self.client = get_client()
        self.recreated = self._ensure_collection()

    def _existing_dim(self) -> int | None:
        try:
            info = self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            # Unnamed vector config exposes `.size`; named configs are a dict.
            if hasattr(vectors, "size"):
                return int(vectors.size)
            if isinstance(vectors, dict) and vectors:
                first = next(iter(vectors.values()))
                return int(getattr(first, "size", 0)) or None
        except Exception:
            return None
        return None

    def _create(self) -> None:
        self.client.create_collection(
            self.collection,
            vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
        )

    def _ensure_collection(self) -> bool:
        """Return True if the collection had to be (re)created with a fresh dim."""
        if not self.client.collection_exists(self.collection):
            self._create()
            return True
        existing = self._existing_dim()
        if existing is not None and existing != self.dim:
            # Dimension changed (e.g. embedding model swapped). Rebuild empty;
            # the Brain will re-index this project's vault afterwards.
            self.client.delete_collection(self.collection)
            self._create()
            return True
        return False

    @staticmethod
    def _point_id(note_id: str, chunk_index: int) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{note_id}:{chunk_index}"))

    def upsert_note(self, note, vectors: list[list[float]], chunks: list[str]) -> None:
        self.delete_note(note.id)
        points = []
        for idx, (vec, chunk) in enumerate(zip(vectors, chunks, strict=False)):
            points.append(
                PointStruct(
                    id=self._point_id(note.id, idx),
                    vector=vec,
                    payload={
                        "note_id": note.id,
                        "title": note.title,
                        "project": note.project,
                        "category": note.category,
                        "tags": note.tags,
                        "agent": note.agent,
                        "source": note.source,
                        "created": note.created,
                        "updated": note.updated,
                        "usefulness": int(getattr(note, "usefulness", 0) or 0),
                        "chunk_index": idx,
                        "text": chunk,
                    },
                )
            )
        if points:
            self.client.upsert(self.collection, points=points)

    def delete_note(self, note_id: str) -> None:
        self.client.delete(
            self.collection,
            points_selector=Filter(
                must=[FieldCondition(key="note_id", match=MatchValue(value=note_id))]
            ),
        )

    def search(
        self,
        vector: list[float],
        limit: int = 8,
        category: str | None = None,
        agent: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        must = []
        if category:
            must.append(FieldCondition(key="category", match=MatchValue(value=category)))
        if agent:
            must.append(FieldCondition(key="agent", match=MatchValue(value=agent)))
        if tag:
            must.append(FieldCondition(key="tags", match=MatchValue(value=tag)))
        flt = Filter(must=must) if must else None
        res = self.client.query_points(
            self.collection, query=vector, limit=limit, query_filter=flt, with_payload=True
        ).points
        out = []
        for p in res:
            payload = dict(p.payload or {})
            payload["score"] = round(float(p.score), 4)
            out.append(payload)
        return out

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def reset(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
        self._create()

    def drop(self) -> None:
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
