"""Command-line client for the Company Brain v2. Talks to the REST API, so it
works from anywhere with BRAIN_URL + BRAIN_API_KEY set.

Examples:
    export BRAIN_URL=https://brain.example.com BRAIN_API_KEY=xxxx
    brain save "Use Qdrant + FastAPI" --project avedit --tag infra
    brain search "what stack" --project avedit
    brain ingest "long conversation text..." --project avedit
    brain feedback <id> --project avedit
    brain projects
    brain consolidate --project avedit
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

BASE = os.getenv("BRAIN_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("BRAIN_API_KEY", "")
AGENT = os.getenv("BRAIN_AGENT", "cli")
PROJECT = os.getenv("BRAIN_PROJECT", "default")
VERIFY = os.getenv("BRAIN_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}


def _client() -> httpx.Client:
    headers = {"Authorization": f"Bearer {KEY}", "X-Agent": AGENT}
    return httpx.Client(base_url=BASE, headers=headers, timeout=60, verify=VERIFY)


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _proj(a) -> str:
    return getattr(a, "project", None) or PROJECT


def _post(path, payload):
    with _client() as c:
        r = c.post(path, json=payload)
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return None
    return r.json()


def cmd_save(a):
    d = _post(
        "/save",
        {
            "content": a.content,
            "title": a.title,
            "category": a.category,
            "tags": a.tag or [],
            "source": a.source or "",
            "project": _proj(a),
        },
    )
    if d is None:
        return 1
    if d.get("duplicate"):
        print(f"already present id={d['id']} (similarity {d.get('similarity')})")
    else:
        print(f"saved id={d['id']} project={d['project']} ({d.get('chunks', 0)} chunks)")
    return 0


def cmd_ingest(a):
    d = _post("/ingest", {"text": a.text, "title": a.title, "project": _proj(a)})
    if d is None:
        return 1
    print(f"ingested id={d['id']} project={d['project']}")
    return 0


def cmd_search(a):
    payload = {"query": a.query, "limit": a.limit, "project": _proj(a)}
    if a.category:
        payload["category"] = a.category
    if a.agent:
        payload["agent"] = a.agent
    d = _post("/search", payload)
    if d is None:
        return 1
    hits = d.get("results", [])
    if not hits:
        print("no results")
        return 0
    for h in hits:
        score = h.get("final_score", h.get("score"))
        print(f"[{score}] {h.get('title')} (id={h.get('note_id')}, by={h.get('agent')})")
        print(f"    {h.get('text', '')[:200]}")
    return 0


def cmd_feedback(a):
    d = _post("/feedback", {"note_id": a.id, "useful": not a.down, "project": _proj(a)})
    if d is None:
        return 1
    print(f"id={d['id']} usefulness={d['usefulness']}")
    return 0


def cmd_consolidate(a):
    with _client() as c:
        r = c.post("/maintenance/consolidate", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def _get(path, params=None):
    with _client() as c:
        r = c.get(path, params=params or {})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def cmd_recent(a):
    return _get("/recent", {"n": a.n, "project": _proj(a)})


def cmd_activity(a):
    params = {"n": a.n, "project": _proj(a)}
    if a.who:
        params["who"] = a.who
    return _get("/activity", params)


def cmd_get(a):
    return _get(f"/get/{a.id}", {"project": _proj(a)})


def cmd_stats(a):
    return _get("/stats", {"project": _proj(a)})


def cmd_projects(a):
    return _get("/projects")


def cmd_reindex(a):
    with _client() as c:
        r = c.post("/reindex", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def cmd_recall(a):
    d = _post("/recall", {"query": a.query, "project": _proj(a)})
    if d is None:
        return 1
    print(d.get("context") or "(no context)")
    print(f"\n[~{d.get('approx_tokens')} tokens · order: {', '.join(d.get('priority_order', []))}]")
    return 0


def cmd_related(a):
    return _get(f"/related/{a.id}", {"project": _proj(a)})


def cmd_entities(a):
    return _get("/entities", {"project": _proj(a)})


def cmd_soul(a):
    return _get("/soul", {"project": _proj(a)})


def cmd_learn(a):
    d = _post("/soul/learn", {"principle": a.principle, "project": _proj(a)})
    return 0 if d is not None else 1


def cmd_pref(a):
    d = _post("/preferences", {"key": a.key, "value": a.value, "project": _proj(a)})
    if d is None:
        return 1
    _print(d)
    return 0


def cmd_dream(a):
    with _client() as c:
        r = c.post("/maintenance/dream", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def cmd_tick(a):
    with _client() as c:
        r = c.post("/maintenance/tick", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def cmd_fact(a):
    d = _post(
        "/facts",
        {"subject": a.subject, "value": a.value, "predicate": a.predicate, "project": _proj(a)},
    )
    if d is None:
        return 1
    _print(d)
    return 0


def cmd_facts(a):
    params = {"project": _proj(a)}
    if a.subject:
        params["subject"] = a.subject
    return _get("/facts", params)


def cmd_doctor(a):
    return _get("/doctor", {"project": _proj(a)})


def cmd_block(a):
    d = _post("/blocks", {"name": a.name, "text": a.text, "project": _proj(a)})
    return 0 if d is not None else 1


def cmd_archive(a):
    d = _post("/archive", {"note_id": a.id, "archived": not a.unarchive, "project": _proj(a)})
    if d is None:
        return 1
    _print(d)
    return 0


def cmd_communities(a):
    return _get("/communities", {"project": _proj(a)})


def cmd_metrics(a):
    return _get("/metrics", {})


def cmd_export(a):
    with _client() as c:
        r = c.get("/export", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    out = a.out or f"{_proj(a)}-export.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(r.json(), f, indent=2, ensure_ascii=False)
    print(f"exported to {out}")
    return 0


def cmd_import(a):
    with open(a.file, encoding="utf-8") as f:
        bundle = json.load(f)
    d = _post("/import", {"bundle": bundle, "project": _proj(a)})
    if d is None:
        return 1
    _print(d)
    return 0


def cmd_sleep(a):
    with _client() as c:
        r = c.post("/maintenance/sleep", params={"project": _proj(a)})
    if r.status_code != 200:
        print(f"error {r.status_code}: {r.text}", file=sys.stderr)
        return 1
    _print(r.json())
    return 0


def cmd_eval(a):
    from brain import evaluate

    with open(a.file, encoding="utf-8") as f:
        dataset = json.load(f)

    def _search(query, project):
        d = _post("/search", {"query": query, "limit": a.k, "project": project or _proj(a)})
        return (d or {}).get("results", [])

    metrics = evaluate.run(_search, dataset, k=a.k)
    print(
        f"cases={metrics['cases']}  recall@{metrics['k']}={metrics['recall_at_k']}  "
        f"mrr={metrics['mrr']}"
    )
    return 0


def _add_project(p):
    p.add_argument(
        "--project", default=None, help="project name (default: $BRAIN_PROJECT or 'default')"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brain", description="Company Brain CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("save", help="store a memory")
    s.add_argument("content")
    s.add_argument("--title", default=None)
    s.add_argument("--category", default="notes")
    s.add_argument("--tag", action="append")
    s.add_argument("--source", default="")
    _add_project(s)
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("ingest", help="capture conversation text")
    s.add_argument("text")
    s.add_argument("--title", default=None)
    _add_project(s)
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("search", help="semantic search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--category", default=None)
    s.add_argument("--agent", default=None)
    _add_project(s)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("feedback", help="mark a memory useful (or --down)")
    s.add_argument("id")
    s.add_argument("--down", action="store_true", help="mark as not useful")
    _add_project(s)
    s.set_defaults(func=cmd_feedback)

    s = sub.add_parser("recent", help="latest memories")
    s.add_argument("-n", type=int, default=20)
    _add_project(s)
    s.set_defaults(func=cmd_recent)

    s = sub.add_parser("activity", help="per-agent activity")
    s.add_argument("--who", default=None)
    s.add_argument("-n", type=int, default=20)
    _add_project(s)
    s.set_defaults(func=cmd_activity)

    s = sub.add_parser("get", help="fetch one memory by id")
    s.add_argument("id")
    _add_project(s)
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("stats", help="brain stats")
    _add_project(s)
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("consolidate", help="merge near-duplicate memories")
    _add_project(s)
    s.set_defaults(func=cmd_consolidate)

    s = sub.add_parser("reindex", help="rebuild index from vault")
    _add_project(s)
    s.set_defaults(func=cmd_reindex)

    s = sub.add_parser("recall", help="multi-layer recall (soul + prefs + memories + procedures)")
    s.add_argument("query")
    _add_project(s)
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("related", help="memories related to a memory id")
    s.add_argument("id")
    _add_project(s)
    s.set_defaults(func=cmd_related)

    s = sub.add_parser("entities", help="list knowledge-graph entities")
    _add_project(s)
    s.set_defaults(func=cmd_entities)

    s = sub.add_parser("soul", help="show the project's SOUL (self-context)")
    _add_project(s)
    s.set_defaults(func=cmd_soul)

    s = sub.add_parser("learn", help="append a learned principle to SOUL")
    s.add_argument("principle")
    _add_project(s)
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("pref", help="set a preference (key value)")
    s.add_argument("key")
    s.add_argument("value")
    _add_project(s)
    s.set_defaults(func=cmd_pref)

    s = sub.add_parser("dream", help="reflection: merge dupes + synthesize digests")
    _add_project(s)
    s.set_defaults(func=cmd_dream)

    s = sub.add_parser("tick", help="heartbeat: decay unused + consolidate")
    _add_project(s)
    s.set_defaults(func=cmd_tick)

    sub.add_parser("projects", help="list all projects").set_defaults(func=cmd_projects)

    # --- v0.0.1.3 ---
    s = sub.add_parser("fact", help="record a bi-temporal fact (supersedes prior)")
    s.add_argument("subject")
    s.add_argument("value")
    s.add_argument("--predicate", default="is")
    _add_project(s)
    s.set_defaults(func=cmd_fact)

    s = sub.add_parser("facts", help="show current facts (optionally for a subject)")
    s.add_argument("subject", nargs="?", default="")
    _add_project(s)
    s.set_defaults(func=cmd_facts)

    s = sub.add_parser("doctor", help="audit memory quality")
    _add_project(s)
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("block", help="set a core memory block (name text)")
    s.add_argument("name")
    s.add_argument("text")
    _add_project(s)
    s.set_defaults(func=cmd_block)

    s = sub.add_parser("archive", help="archive a memory (or --unarchive)")
    s.add_argument("id")
    s.add_argument("--unarchive", action="store_true")
    _add_project(s)
    s.set_defaults(func=cmd_archive)

    s = sub.add_parser("communities", help="detect entity communities")
    _add_project(s)
    s.set_defaults(func=cmd_communities)

    sub.add_parser("metrics", help="usage counters").set_defaults(func=cmd_metrics)

    s = sub.add_parser("export", help="export a project to a JSON bundle")
    s.add_argument("--out", default="")
    _add_project(s)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("import", help="import a project from a JSON bundle")
    s.add_argument("file")
    _add_project(s)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("sleep", help="sleep cycle: dream + (optional) archive + audit")
    _add_project(s)
    s.set_defaults(func=cmd_sleep)

    s = sub.add_parser("eval", help="run a retrieval eval dataset (recall@k + MRR)")
    s.add_argument("file")
    s.add_argument("--k", type=int, default=5)
    _add_project(s)
    s.set_defaults(func=cmd_eval)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not KEY:
        print("BRAIN_API_KEY is not set", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
