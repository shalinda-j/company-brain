"""A tiny retrieval-evaluation harness.

Given a dataset of {query, expected (note ids), project}, run search and compute
recall@k and mean reciprocal rank (MRR) — so you can tell whether a change to
retrieval actually improved quality, rather than guessing.
"""

from __future__ import annotations


def recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected:
        return 0.0
    top = set(retrieved[:k])
    hit = sum(1 for e in expected if e in top)
    return hit / len(expected)


def reciprocal_rank(expected: list[str], retrieved: list[str]) -> float:
    exp = set(expected)
    for i, rid in enumerate(retrieved):
        if rid in exp:
            return 1.0 / (i + 1)
    return 0.0


def run(search_fn, dataset: list[dict], k: int = 5) -> dict:
    """search_fn(query, project) -> list of hit dicts (with note_id)."""
    recalls, rrs, per = [], [], []
    for case in dataset:
        query = case["query"]
        expected = case.get("expected", [])
        project = case.get("project")
        hits = search_fn(query, project)
        retrieved = [h.get("note_id") for h in hits]
        r = recall_at_k(expected, retrieved, k)
        rr = reciprocal_rank(expected, retrieved)
        recalls.append(r)
        rrs.append(rr)
        per.append({"query": query, "recall_at_k": round(r, 3), "rr": round(rr, 3)})
    n = len(dataset) or 1
    return {
        "cases": len(dataset),
        "k": k,
        "recall_at_k": round(sum(recalls) / n, 4),
        "mrr": round(sum(rrs) / n, 4),
        "per_case": per,
    }
