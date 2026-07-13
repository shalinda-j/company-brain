"""MCP server tests: tool functions exercised via httpx.MockTransport (no
network, no real brain). httpx.Client is intercepted below srv._client so the
real header/base-url wiring is exercised too."""

from __future__ import annotations

import httpx
import pytest

import mcp_server.server as srv


@pytest.fixture()
def transport(monkeypatch):
    """Route every request built by srv._client() through a MockTransport.

    Returns a dict the test fills: {path: (status, json)}. Every request is
    recorded in `calls`.
    """
    routes: dict[str, tuple[int, object]] = {}
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        # The real _client() must attach the API key on every request.
        assert request.headers.get("authorization", "").startswith("Bearer ")
        status, payload = routes.get(request.url.path, (500, {"detail": "unrouted"}))
        return httpx.Response(status, json=payload)

    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(srv.httpx, "Client", patched_client)
    routes["calls"] = calls  # type: ignore[assignment]
    return routes


def test_all_new_tools_registered():
    names = {t.name for t in srv.mcp._tool_manager.list_tools()}
    for tool in (
        "brain_save",
        "brain_search",
        "brain_get",
        "brain_delete",
        "brain_archive",
        "brain_pin",
        "brain_checkpoint",
        "brain_resume",
        "brain_session_close",
    ):
        assert tool in names


def test_brain_save_new_and_duplicate(transport):
    transport["/save"] = (200, {"id": "n1", "project": "p", "chunks": 2, "duplicate": False})
    out = srv.brain_save("remember this", title="t", project="p")
    assert "Saved id=n1" in out and "'p'" in out

    transport["/save"] = (200, {"id": "n1", "duplicate": True, "similarity": 0.99})
    out = srv.brain_save("remember this", project="p")
    assert "Already in brain" in out and "n1" in out


def test_brain_search_results_and_empty(transport):
    transport["/search"] = (
        200,
        {
            "results": [
                {
                    "note_id": "n1",
                    "title": "hit",
                    "final_score": 0.9,
                    "category": "notes",
                    "agent": "a",
                    "text": "body",
                }
            ]
        },
    )
    out = srv.brain_search("query")
    assert "hit" in out and "id=n1" in out

    transport["/search"] = (200, {"results": []})
    assert srv.brain_search("query") == "No relevant memories found."


def test_brain_get_404(transport):
    transport["/get/nope"] = (404, {"detail": "Not found"})
    assert srv.brain_get("nope") == "No memory with id=nope."


def test_brain_delete(transport):
    transport["/delete/n1"] = (200, {"deleted": "n1"})
    assert srv.brain_delete("n1") == "Deleted id=n1."
    transport["/delete/gone"] = (404, {"detail": "Not found"})
    assert srv.brain_delete("gone") == "No memory with id=gone."
    req = [c for c in transport["calls"] if c.url.path == "/delete/n1"][0]
    assert req.method == "DELETE"


def test_brain_archive_and_pin(transport):
    transport["/archive"] = (200, {"id": "n1", "archived": True})
    assert "Archived id=n1" in srv.brain_archive("n1")
    assert "Unarchived id=n1" in srv.brain_archive("n1", archived=False)
    transport["/pin"] = (200, {"id": "n1", "pinned": True})
    assert "Pinned id=n1" in srv.brain_pin("n1")
    assert "Unpinned id=n1" in srv.brain_pin("n1", pinned=False)


def test_brain_session_close(transport):
    transport["/session/close"] = (200, {"summary_note_id": "sum1", "checkpoints": 4})
    out = srv.brain_session_close(project="p", session="s1")
    assert "4 checkpoints" in out and "sum1" in out

    transport["/session/close"] = (200, {"summary_note_id": None, "checkpoints": 0})
    out = srv.brain_session_close(session="empty")
    assert "no summary created" in out


def test_error_translation_auth(transport):
    transport["/search"] = (401, {"detail": "Invalid API key"})
    with pytest.raises(RuntimeError, match="authentication failed"):
        srv.brain_search("q")
    transport["/search"] = (403, {"detail": "Requires 'read' role"})
    with pytest.raises(RuntimeError, match="authentication failed"):
        srv.brain_search("q")


def test_error_translation_server_and_client_errors(transport):
    transport["/search"] = (500, {"detail": "boom"})
    with pytest.raises(RuntimeError, match="server error 500"):
        srv.brain_search("q")
    transport["/save"] = (422, {"detail": "Field required"})
    with pytest.raises(RuntimeError, match="brain error 422: Field required"):
        srv.brain_save("x")


def test_error_translation_unreachable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    real_client = httpx.Client
    monkeypatch.setattr(
        srv.httpx,
        "Client",
        lambda *a, **kw: real_client(*a, **{**kw, "transport": httpx.MockTransport(handler)}),
    )
    with pytest.raises(RuntimeError, match="unreachable"):
        srv.brain_search("q")


def test_check_pass_and_bad_key(transport, monkeypatch, capsys):
    monkeypatch.setenv("BRAIN_URL", srv.BRAIN_URL)
    monkeypatch.setenv("BRAIN_API_KEY", "k")
    transport["/health"] = (200, {"status": "ok", "version": "0.2.0", "auth": True})
    transport["/projects"] = (200, {"projects": []})
    assert srv._check() == 0
    assert "PASS" in capsys.readouterr().out

    transport["/projects"] = (401, {"detail": "Invalid API key"})
    assert srv._check() == 1
    assert "FAIL" in capsys.readouterr().out
