"""A deterministic, dependency-free embedder for tests and CI.

It hashes character trigrams into a fixed-size vector, so semantically
overlapping text produces similar vectors — enough to exercise the full
search pipeline without downloading any model.
"""

from __future__ import annotations

import hashlib
import math

DIM = 96


class FakeEmbedder:
    dim = DIM

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        t = f"  {text.lower()} "
        for i in range(len(t) - 2):
            tri = t[i : i + 3]
            h = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
            v[h % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)
