"""Hybrid retrieval helpers: a small in-process BM25 plus Reciprocal Rank Fusion.

Dense (vector) retrieval is great at meaning; BM25 is great at exact keywords and
rare terms. We fuse the two ranked lists with RRF, which operates on ranks and so
sidesteps the incompatible score scales of cosine vs BM25.
"""

from __future__ import annotations

import math
import re

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def bm25_index(docs: list[tuple[str, str]]) -> dict:
    """Precompute per-corpus BM25 stats once; rank many queries against it
    with bm25_rank_indexed. docs: list of (doc_id, text)."""
    tf_by_doc: dict[str, dict[str, int]] = {}
    lengths: dict[str, int] = {}
    df: dict[str, int] = {}
    for doc_id, text in docs:
        toks = tokenize(text)
        lengths[doc_id] = len(toks)
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        tf_by_doc[doc_id] = tf
        for term in tf:
            df[term] = df.get(term, 0) + 1
    n = len(tf_by_doc)
    avgdl = (sum(lengths.values()) / n) if n else 0.0
    return {"tf": tf_by_doc, "lengths": lengths, "df": df, "n": n, "avgdl": avgdl}


def bm25_rank_indexed(
    query: str, index: dict, k1: float = 1.5, b: float = 0.75
) -> list[tuple[str, float]]:
    """Rank a prebuilt bm25_index. Docs with score <= 0 (no matching term) are
    dropped so non-matching docs earn no RRF credit downstream."""
    n, avgdl, df = index["n"], index["avgdl"], index["df"]
    if not n:
        return []
    q_terms = [t for t in set(tokenize(query)) if t in df]
    scores: list[tuple[str, float]] = []
    for doc_id, tf in index["tf"].items():
        dl = index["lengths"][doc_id]
        score = 0.0
        for term in q_terms:
            f = tf.get(term, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = f + k1 * (1 - b + b * dl / avgdl) if avgdl else f + k1
            score += idf * (f * (k1 + 1)) / denom
        if score > 0:
            scores.append((doc_id, score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def bm25_rank(
    query: str, docs: list[tuple[str, str]], k1: float = 1.5, b: float = 0.75
) -> list[tuple[str, float]]:
    """docs: list of (doc_id, text). Returns [(doc_id, score)] ranked desc."""
    return bm25_rank_indexed(query, bm25_index(docs), k1=k1, b=b)


def rrf_fuse(*ranked_lists: list[str], k: int = 60) -> list[tuple[str, float]]:
    """Each input is an ordered list of ids (best first). Returns fused order."""
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    out = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    return out
