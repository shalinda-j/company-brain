"""Company Brain v2 MCP server (the portable connector).

Runs wherever your AI client runs (Claude Code, Cursor, ...) and forwards tool
calls to your brain's REST API over HTTPS. Carry BRAIN_URL + BRAIN_API_KEY and
connect from anywhere — no model weights, no GPU.

Env:
  BRAIN_URL          e.g. https://brain.example.com   (required)
  BRAIN_API_KEY      your API key                       (required)
  BRAIN_AGENT        identity for this client           (default: mcp-client)
  BRAIN_PROJECT      default project for this client    (default: default)
  BRAIN_VERIFY_TLS   set false for self-signed certs    (default: true)

Tools: brain_save, brain_ingest, brain_search, brain_get, brain_recent,
brain_activity, brain_feedback, brain_projects, brain_consolidate.
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

BRAIN_URL = os.getenv("BRAIN_URL", "http://localhost:8000").rstrip("/")
BRAIN_API_KEY = os.getenv("BRAIN_API_KEY", "")
AGENT_NAME = os.getenv("BRAIN_AGENT", "mcp-client")
DEFAULT_PROJECT = os.getenv("BRAIN_PROJECT", "default")
TIMEOUT = float(os.getenv("BRAIN_TIMEOUT", "30"))
VERIFY_TLS = os.getenv("BRAIN_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}

mcp = FastMCP("company-brain")


def _client() -> httpx.Client:
    headers = {
        "Authorization": f"Bearer {BRAIN_API_KEY}",
        "Content-Type": "application/json",
        "X-Agent": AGENT_NAME,
    }
    return httpx.Client(base_url=BRAIN_URL, headers=headers, timeout=TIMEOUT, verify=VERIFY_TLS)


def _proj(project: str) -> str:
    return project or DEFAULT_PROJECT


@mcp.tool()
def brain_save(
    content: str,
    title: str = "",
    category: str = "notes",
    tags: list[str] | None = None,
    source: str = "",
    project: str = "",
) -> str:
    """Save a memory to the brain. category: conversations|notes|tasks|knowledge.
    project isolates memories (e.g. 'avedit', 'weddinghub'). Near-duplicates are
    detected and not stored twice."""
    payload = {
        "content": content,
        "title": title or None,
        "category": category,
        "tags": tags or [],
        "source": source,
        "project": _proj(project),
    }
    with _client() as c:
        r = c.post("/save", json=payload)
        r.raise_for_status()
        d = r.json()
    if d.get("duplicate"):
        return (
            f"Already in brain as id={d['id']} (similarity {d.get('similarity')}). Not duplicated."
        )
    return f"Saved id={d['id']} in project '{d['project']}' ({d.get('chunks', 0)} chunks)."


@mcp.tool()
def brain_ingest(
    text: str, title: str = "", source: str = "conversation", project: str = ""
) -> str:
    """Capture conversation text as a memory. Use at the end of a task to remember
    what was decided/done (optionally auto-summarized if the server is configured)."""
    payload = {"text": text, "title": title or None, "source": source, "project": _proj(project)}
    with _client() as c:
        r = c.post("/ingest", json=payload)
        r.raise_for_status()
        d = r.json()
    return f"Captured id={d['id']} in project '{d['project']}'."


@mcp.tool()
def brain_search(
    query: str, limit: int = 8, category: str = "", agent: str = "", project: str = ""
) -> str:
    """Semantically search the brain. Filter by category, by the agent who wrote a
    memory, and by project. Results are ranked by relevance + usefulness."""
    payload = {"query": query, "limit": limit, "project": _proj(project)}
    if category:
        payload["category"] = category
    if agent:
        payload["agent"] = agent
    with _client() as c:
        r = c.post("/search", json=payload)
        r.raise_for_status()
        hits = r.json().get("results", [])
    if not hits:
        return "No relevant memories found."
    lines = []
    for h in hits:
        lines.append(
            f"[{h.get('final_score', h.get('score'))}] {h.get('title')} "
            f"(id={h.get('note_id')}, cat={h.get('category')}, by={h.get('agent')})\n"
            f"    {h.get('text', '')[:300]}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def brain_get(note_id: str, project: str = "") -> str:
    """Fetch one memory in full by its id."""
    with _client() as c:
        r = c.get(f"/get/{note_id}", params={"project": _proj(project)})
        if r.status_code == 404:
            return f"No memory with id={note_id}."
        r.raise_for_status()
        n = r.json()
    header = (
        f"# {n['title']}\n"
        f"(id={n['id']}, project={n['project']}, category={n['category']}, "
        f"agent={n['agent']}, updated={n['updated']}, usefulness={n.get('usefulness', 0)})\n"
        f"tags: {', '.join(n.get('tags', []))}"
    )
    return f"{header}\n\n{n['content']}"


@mcp.tool()
def brain_recent(n: int = 20, project: str = "") -> str:
    """List the most recently updated memories in a project."""
    with _client() as c:
        r = c.get("/recent", params={"n": n, "project": _proj(project)})
        r.raise_for_status()
        items = r.json().get("results", [])
    if not items:
        return "No memories yet."
    return "\n".join(
        f"- {i['updated']}  [{i['category']}] {i['title']} (id={i['id']}, by={i['agent']})"
        for i in items
    )


@mcp.tool()
def brain_activity(who: str = "", n: int = 20, project: str = "") -> str:
    """See what agents have been doing in a project. Pass `who` to filter to one
    agent — useful for seeing what other AI agents did."""
    params = {"n": n, "project": _proj(project)}
    if who:
        params["who"] = who
    with _client() as c:
        r = c.get("/activity", params=params)
        r.raise_for_status()
        items = r.json().get("results", [])
    if not items:
        return "No activity recorded."
    return "\n".join(
        f"- {i['updated']}  {i['agent']}  [{i['category']}] {i['title']} (id={i['id']})"
        for i in items
    )


@mcp.tool()
def brain_feedback(note_id: str, useful: bool = True, project: str = "") -> str:
    """Mark a memory as useful (or not). Useful memories rank higher in future
    searches."""
    payload = {"note_id": note_id, "useful": useful, "project": _proj(project)}
    with _client() as c:
        r = c.post("/feedback", json=payload)
        if r.status_code == 404:
            return f"No memory with id={note_id}."
        r.raise_for_status()
        d = r.json()
    return f"Updated id={d['id']} usefulness={d['usefulness']}."


@mcp.tool()
def brain_projects() -> str:
    """List all projects in the brain with their memory counts."""
    with _client() as c:
        r = c.get("/projects")
        r.raise_for_status()
        items = r.json().get("projects", [])
    if not items:
        return "No projects yet."
    return "\n".join(f"- {p['project']}: {p['notes']} notes, {p['vectors']} vectors" for p in items)


@mcp.tool()
def brain_consolidate(project: str = "") -> str:
    """Self-optimize a project: merge near-duplicate memories into one."""
    with _client() as c:
        r = c.post("/maintenance/consolidate", params={"project": _proj(project)})
        r.raise_for_status()
        d = r.json()
    return (
        f"Consolidated project '{d['project']}': merged/removed {d['removed']} duplicate memories."
    )


@mcp.tool()
def brain_recall(query: str, project: str = "") -> str:
    """Multi-layer recall: pulls the agent's SOUL, preferences, the most relevant
    memories, procedures, and related entities into one token-budgeted context
    bundle. Use this at the START of a task to load everything relevant at once."""
    payload = {"query": query, "project": _proj(project)}
    with _client() as c:
        r = c.post("/recall", json=payload)
        r.raise_for_status()
        d = r.json()
    return d.get("context") or "No context found."


@mcp.tool()
def brain_related(note_id: str, project: str = "") -> str:
    """Find memories related to a given memory (by shared entities + similarity)."""
    with _client() as c:
        r = c.get(f"/related/{note_id}", params={"project": _proj(project)})
        r.raise_for_status()
        items = r.json().get("related", [])
    if not items:
        return "No related memories."
    return "\n".join(
        f"- {i.get('title')} (id={i.get('note_id')}, {i.get('reason')})" for i in items
    )


@mcp.tool()
def brain_entities(project: str = "") -> str:
    """List the knowledge-graph entities in a project (people, topics, things)
    with how often each is mentioned."""
    with _client() as c:
        r = c.get("/entities", params={"project": _proj(project)})
        r.raise_for_status()
        items = r.json().get("entities", [])
    if not items:
        return "No entities yet. Mention them with [[wikilinks]] or #hashtags."
    return "\n".join(f"- {e['entity']} ({e['mentions']})" for e in items[:40])


@mcp.tool()
def brain_learn(principle: str, project: str = "") -> str:
    """Teach the brain a durable principle about how to work — it's appended to the
    project's SOUL and surfaced in every future recall."""
    with _client() as c:
        r = c.post("/soul/learn", json={"principle": principle, "project": _proj(project)})
        r.raise_for_status()
    return "Learned. It will appear in future recalls."


@mcp.tool()
def brain_remember_preference(key: str, value: str, project: str = "") -> str:
    """Store a user/agent preference (key + value). Preferences are surfaced in
    every recall."""
    with _client() as c:
        r = c.post("/preferences", json={"key": key, "value": value, "project": _proj(project)})
        r.raise_for_status()
    return f"Saved preference {key} = {value}."


@mcp.tool()
def brain_dream(project: str = "") -> str:
    """Run a reflection pass: merge duplicates and synthesize digest notes from
    clusters of related memories (self-optimization)."""
    with _client() as c:
        r = c.post("/maintenance/dream", params={"project": _proj(project)})
        r.raise_for_status()
        d = r.json()
    return (
        f"Dreamed on '{d['project']}': merged {d['consolidated']} duplicates, "
        f"created {d['digests_created']} digests."
    )


@mcp.tool()
def brain_remember_fact(subject: str, value: str, predicate: str = "is", project: str = "") -> str:
    """Record a fact about a subject. If a fact for the same subject already exists,
    it's superseded (the old one is kept as history). Use for facts that change —
    status, plan, current value, etc."""
    payload = {
        "subject": subject,
        "value": value,
        "predicate": predicate,
        "project": _proj(project),
    }
    with _client() as c:
        r = c.post("/facts", json=payload)
        r.raise_for_status()
        d = r.json()
    inv = len(d.get("invalidated", []))
    extra = f" (superseded {inv} prior)" if inv else ""
    return f"Recorded: {subject} {predicate} {value}.{extra}"


@mcp.tool()
def brain_facts(subject: str = "", project: str = "") -> str:
    """Get current (non-superseded) facts, optionally for one subject."""
    params = {"project": _proj(project)}
    if subject:
        params["subject"] = subject
    with _client() as c:
        r = c.get("/facts", params=params)
        r.raise_for_status()
        items = r.json().get("facts", [])
    if not items:
        return "No facts."
    return "\n".join(f"- {f['subject']} {f['predicate']} {f['value']}" for f in items)


@mcp.tool()
def brain_set_block(name: str, text: str, project: str = "") -> str:
    """Write a core memory block (e.g. 'human' = facts about the user). Blocks are
    size-limited and always included in recall."""
    with _client() as c:
        r = c.post("/blocks", json={"name": name, "text": text, "project": _proj(project)})
        r.raise_for_status()
    return f"Block '{name}' saved."


@mcp.tool()
def brain_doctor(project: str = "") -> str:
    """Audit memory quality: duplicates, stale items, orphan entities, oversized
    blocks, possible secrets/PII, and contradictory facts."""
    with _client() as c:
        r = c.get("/doctor", params={"project": _proj(project)})
        r.raise_for_status()
        s = r.json().get("summary", {})
    return "Memory health — " + ", ".join(f"{k}: {v}" for k, v in s.items())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
