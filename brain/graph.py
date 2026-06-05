"""Knowledge-graph layer.

Entities are extracted heuristically (no LLM) from [[wikilinks]], #hashtags, and
an explicit entities field, then canonicalized via brain.resolve so surface
variants collapse into one node. On top of the entity/co-occurrence graph we add
community detection (label propagation) and multi-hop traversal. The graph is
computed on demand from the vault, which remains the source of truth.

Optional LLM-based triple extraction and LLM community summaries are intentionally
left as documented hooks (see CAPABILITIES.md); the algorithmic pieces below are
fully local.
"""

from __future__ import annotations

import re

from . import resolve, vault

_WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
_HASHTAG = re.compile(r"(?<!\w)#([A-Za-z][\w-]{1,40})")


def extract_entities(content: str, explicit: list[str] | None = None) -> list[str]:
    found: list[str] = []
    for m in _WIKILINK.findall(content or ""):
        found.append(m.strip())
    for m in _HASHTAG.findall(content or ""):
        found.append(m.strip())
    for e in explicit or []:
        if e and e.strip():
            found.append(e.strip())
    seen: dict[str, str] = {}
    for e in found:
        key = e.lower()
        if key not in seen:
            seen[key] = e
    return list(seen.values())


def _canon_entities(ents: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for e in ents:
        c = resolve.canonical(e)
        if c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def build_graph(project: str) -> dict:
    entities: dict[str, int] = {}
    edges: dict[str, int] = {}
    note_entities: dict[str, list[str]] = {}
    for note, _ in vault.iter_notes(project):
        ents = _canon_entities(note.entities or [])
        note_entities[note.id] = ents
        for e in ents:
            entities[e] = entities.get(e, 0) + 1
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = sorted([ents[i], ents[j]])
                key = f"{a}|||{b}"
                edges[key] = edges.get(key, 0) + 1
    return {"entities": entities, "edges": edges, "note_entities": note_entities}


def entity_list(project: str) -> list[dict]:
    g = build_graph(project)
    items = [{"entity": e, "mentions": c} for e, c in g["entities"].items()]
    items.sort(key=lambda x: x["mentions"], reverse=True)
    return items


def _adjacency(project: str) -> dict[str, dict[str, int]]:
    g = build_graph(project)
    adj: dict[str, dict[str, int]] = {e: {} for e in g["entities"]}
    for key, w in g["edges"].items():
        a, b = key.split("|||")
        adj.setdefault(a, {})[b] = w
        adj.setdefault(b, {})[a] = w
    return adj


def neighbors(project: str, entity: str) -> list[dict]:
    target = resolve.canonical(entity).lower()
    adj = _adjacency(project)
    for name, nbrs in adj.items():
        if name.lower() == target:
            out = [{"entity": k, "weight": v} for k, v in nbrs.items()]
            out.sort(key=lambda x: x["weight"], reverse=True)
            return out
    return []


def multihop(project: str, entity: str, depth: int = 2) -> list[dict]:
    """Breadth-first traversal up to `depth` hops from an entity."""
    adj = _adjacency(project)
    start = None
    target = resolve.canonical(entity).lower()
    for name in adj:
        if name.lower() == target:
            start = name
            break
    if start is None:
        return []
    seen = {start: 0}
    frontier = [start]
    for d in range(1, max(1, depth) + 1):
        nxt = []
        for node in frontier:
            for nbr in adj.get(node, {}):
                if nbr not in seen:
                    seen[nbr] = d
                    nxt.append(nbr)
        frontier = nxt
        if not frontier:
            break
    return sorted(
        ({"entity": e, "distance": dist} for e, dist in seen.items() if e != start),
        key=lambda x: (x["distance"], x["entity"]),
    )


def communities(project: str, max_iters: int = 20) -> list[dict]:
    """Label-propagation community detection over the entity graph."""
    adj = _adjacency(project)
    if not adj:
        return []
    labels = {node: node for node in adj}
    nodes = sorted(adj)
    for _ in range(max_iters):
        changed = False
        for node in nodes:
            nbrs = adj[node]
            if not nbrs:
                continue
            tally: dict[str, float] = {}
            for nbr, w in nbrs.items():
                tally[labels[nbr]] = tally.get(labels[nbr], 0.0) + w
            best = max(sorted(tally), key=lambda lab: tally[lab])
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break
    groups: dict[str, list[str]] = {}
    for node, lab in labels.items():
        groups.setdefault(lab, []).append(node)
    out = [
        {"id": i, "members": sorted(members)}
        for i, members in enumerate(sorted(groups.values(), key=len, reverse=True))
    ]
    return out


def notes_for_entity(project: str, entity: str) -> list[str]:
    target = resolve.canonical(entity).lower()
    out: list[str] = []
    for note, _ in vault.iter_notes(project):
        ents = [resolve.canonical(e).lower() for e in (note.entities or [])]
        if target in ents:
            out.append(note.id)
    return out


def notes_sharing_entities(project: str, note_id: str) -> list[str]:
    base = vault.find_note(project, note_id)
    if not base or not base.entities:
        return []
    base_ents = {resolve.canonical(e).lower() for e in base.entities}
    scored: list[tuple[int, str]] = []
    for note, _ in vault.iter_notes(project):
        if note.id == note_id:
            continue
        other = {resolve.canonical(e).lower() for e in (note.entities or [])}
        shared = len(base_ents & other)
        if shared:
            scored.append((shared, note.id))
    scored.sort(reverse=True)
    return [nid for _, nid in scored]
