"""Company Brain MCP server.

This is the *portable* piece. It runs wherever your AI client runs (Claude Code,
Cursor, etc.) and forwards every tool call to your brain's REST API over HTTPS.
You "take it with you" by carrying two env vars: BRAIN_URL and BRAIN_API_KEY.
No model weights, no GPU, no heavy local install.

Run it as a stdio MCP server:
    BRAIN_URL=https://brain.example.com BRAIN_API_KEY=xxxx python -m mcp_server.server

Tools exposed to the AI:
    brain_save      - remember something
    brain_search    - semantic search across all memories
    brain_get       - read one memory in full
    brain_recent    - list the latest memories
    brain_activity  - see what each agent has been doing (multi-agent visibility)
"""
from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

BRAIN_URL = os.getenv("BRAIN_URL", "http://localhost:8000").rstrip("/")
BRAIN_API_KEY = os.getenv("BRAIN_API_KEY", "")
# This MCP client's own identity, recorded against everything it writes.
AGENT_NAME = os.getenv("BRAIN_AGENT", "mcp-client")
TIMEOUT = float(os.getenv("BRAIN_TIMEOUT", "30"))
VERIFY_TLS = os.getenv("BRAIN_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}

mcp = FastMCP("company-brain")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {BRAIN_API_KEY}",
        "Content-Type": "application/json",
        "X-Agent": AGENT_NAME,
    }


def _client() -> httpx.Client:
    return httpx.Client(base_url=BRAIN_URL, headers=_headers(), timeout=TIMEOUT, verify=VERIFY_TLS)


@mcp.tool()
def brain_save(
    content: str,
    title: str = "",
    category: str = "notes",
    tags: list[str] | None = None,
    source: str = "",
) -> str:
    """Save a memory to the company brain so it can be retrieved later.

    category is one of: conversations, notes, tasks, knowledge.
    Use this to remember decisions, facts, snippets, meeting notes, anything.
    """
    payload = {
        "content": content,
        "title": title or None,
        "category": category,
        "tags": tags or [],
        "source": source,
    }
    with _client() as c:
        r = c.post("/save", json=payload)
        r.raise_for_status()
        data = r.json()
    return f"Saved memory id={data['id']} ({data.get('chunks', 0)} chunks indexed)."


@mcp.tool()
def brain_search(query: str, limit: int = 8, category: str = "", agent: str = "") -> str:
    """Semantically search the company brain. Returns the most relevant memories.

    Optionally filter by category or by the agent who created the memory.
    """
    payload = {"query": query, "limit": limit}
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
            f"[{h.get('score')}] {h.get('title')} "
            f"(id={h.get('note_id')}, cat={h.get('category')}, by={h.get('agent')})\n"
            f"    {h.get('text', '')[:300]}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def brain_get(note_id: str) -> str:
    """Fetch one memory in full by its id."""
    with _client() as c:
        r = c.get(f"/get/{note_id}")
        if r.status_code == 404:
            return f"No memory with id={note_id}."
        r.raise_for_status()
        n = r.json()
    return f"# {n['title']}\n(id={n['id']}, category={n['category']}, agent={n['agent']}, updated={n['updated']})\ntags: {', '.join(n.get('tags', []))}\n\n{n['content']}"


@mcp.tool()
def brain_recent(n: int = 20) -> str:
    """List the most recently updated memories across the whole brain."""
    with _client() as c:
        r = c.get("/recent", params={"n": n})
        r.raise_for_status()
        items = r.json().get("results", [])
    if not items:
        return "Brain is empty."
    return "\n".join(
        f"- {i['updated']}  [{i['category']}] {i['title']} (id={i['id']}, by={i['agent']})"
        for i in items
    )


@mcp.tool()
def brain_activity(who: str = "", n: int = 20) -> str:
    """See what agents have been doing. Pass `who` to filter to one agent.

    Use this to find out what other AI agents connected to this brain have done.
    """
    params = {"n": n}
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
