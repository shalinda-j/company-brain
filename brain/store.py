"""Qdrant vector store. Supports a remote/standalone Qdrant server (recommended
for production via docker-compose) or an embedded on-disk store (zero extra
services, good for tiny deployments). The vault remains the source of truth, so
this index can always be rebuilt with reindex().
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


class VectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.collection = config.qdrant_collection
        if config.qdrant_url:
            self.client = QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key)
        else:
            # Embedded, on-disk. No server required.
            self.client = QdrantClient(path=str(config.qdrant_path))
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        exists = self.client.collection_exists(self.collection)
        if not exists:
            self.client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    @staticmethod
    def _point_id(note_id: str, chunk_index: int) -> str:
        # Deterministic UUID so re-indexing the same chunk overwrites in place.
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{note_id}:{chunk_index}"))

    def upsert_note(self, note, vectors: list[list[float]], chunks: list[str]) -> None:
        # Remove any stale chunks for this note first.
        self.delete_note(note.id)
        points = []
        for idx, (vec, chunk) in enumerate(zip(vectors, chunks)):
            points.append(
                PointStruct(
                    id=self._point_id(note.id, idx),
                    vector=vec,
                    payload={
                        "note_id": note.id,
                        "title": note.title,
                        "category": note.category,
                        "tags": note.tags,
                        "agent": note.agent,
                        "source": note.source,
                        "created": note.created,
                        "updated": note.updated,
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
        self._ensure_collection()
