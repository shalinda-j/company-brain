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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
