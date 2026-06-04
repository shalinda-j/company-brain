"""Embeddings. Runs locally on CPU via fastembed (ONNX) so no GPU and no data
ever leaves the machine.

The default model is multilingual (Sinhala + English + code). Swap it with the
EMBED_MODEL env var. e5 models need "query:"/"passage:" prefixes; we add those
automatically when the model name contains "e5".
"""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local CPU embeddings via fastembed."""

    def __init__(self, model_name: str, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._is_e5 = "e5" in model_name.lower()
        kwargs = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        self._model = TextEmbedding(**kwargs)
        # Probe dimensionality once.
        probe = next(iter(self._model.embed(["dimension probe"])))
        self.dim = len(probe)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._is_e5:
            texts = [f"passage: {t}" for t in texts]
        return [list(map(float, v)) for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        if self._is_e5:
            text = f"query: {text}"
        return list(map(float, next(iter(self._model.embed([text])))))


def get_embedder(model_name: str, cache_dir: str | None = None) -> Embedder:
    return FastEmbedEmbedder(model_name, cache_dir)
