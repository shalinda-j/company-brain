"""REST API tests (v2): health, auth, agent resolution, projects, save/search,
ingest, feedback, consolidate, validation, security headers, audit safety."""

from __future__ import annotations

AAA = {"Authorization": "Bearer test-key-aaa"}  # agent claude-code
BBB = {"Authorization": "Bearer test-key-bbb"}  # agent cursor


def test_health_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["auth"] is True


def test_reject_no_key(client):
    assert client.post("/search", json={"query": "x"}).status_code == 401
    assert client.get("/recent").status_code == 401


def test_reject_bad_key(client):
    r = client.post("/search", json={"query": "x"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_agent_from_key(client):
    r = client.post("/save", json={"content": "from aaa", "title": "t"}, headers=AAA)
    assert r.status_code == 200 and r.json()["agent"] == "claude-code"
    r2 = client.post("/save", json={"content": "from bbb", "title": "t2"}, headers=BBB)
    assert r2.json()["agent"] == "cursor"


def test_save_search_get_flow(client):
    client.post("/save", json={"content": "n8n connects via webhook", "title": "n8n"}, headers=AAA)
    r = client.post("/search", json={"query": "webhook", "limit": 5}, headers=AAA)
    assert r.status_code == 200 and r.json()["results"]
    nid = r.json()["results"][0]["note_id"]
    assert client.get(f"/get/{nid}", headers=AAA).status_code == 200


def test_projects_endpoint(client):
    client.post(
        "/save", json={"content": "alpha stuff", "title": "a", "project": "alpha"}, headers=AAA
    )
    client.post(
        "/save", json={"content": "beta stuff", "title": "b", "project": "beta"}, headers=AAA
    )
    r = client.get("/projects", headers=AAA)
    names = [p["project"] for p in r.json()["projects"]]
    assert "alpha" in names and "beta" in names
    # Isolation at the API level.
    r2 = client.post("/search", json={"query": "beta stuff", "project": "alpha"}, headers=AAA)
    assert all("beta" not in h["title"] for h in r2.json()["results"])


def test_ingest_endpoint(client):
    r = client.post(
        "/ingest", json={"text": "decided to use Caddy for TLS", "project": "p1"}, headers=AAA
    )
    assert r.status_code == 200 and r.json()["category"] == "conversations"


def test_feedback_endpoint(client):
    s = client.post("/save", json={"content": "useful memory", "title": "u"}, headers=AAA).json()
    r = client.post("/feedback", json={"note_id": s["id"], "useful": True}, headers=AAA)
    assert r.status_code == 200 and r.json()["usefulness"] == 1
    assert client.post("/feedback", json={"note_id": "missing"}, headers=AAA).status_code == 404


def test_consolidate_endpoint(client):
    client.post("/save", json={"content": "duplicate line xyz", "title": "d1"}, headers=AAA)
    client.post(
        "/save",
        json={"content": "duplicate line xyz", "title": "d2", "allow_duplicate": True},
        headers=AAA,
    )
    r = client.post("/maintenance/consolidate", headers=AAA)
    assert r.status_code == 200 and r.json()["removed"] >= 1


def test_validation_empty_content(client):
    assert client.post("/save", json={"content": ""}, headers=AAA).status_code == 422


def test_search_limit_bounds(client):
    assert client.post("/search", json={"query": "x", "limit": 999}, headers=AAA).status_code == 422


def test_stats(client):
    r = client.get("/stats", headers=AAA)
    assert r.status_code == 200 and "embed_model" in r.json()


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_audit_no_key_leak(client):
    client.post("/save", json={"content": "audited", "title": "a"}, headers=AAA)
    from brain.config import config

    text = config.audit_log_path.read_text(encoding="utf-8")
    assert '"event": "save"' in text
    assert "test-key-aaa" not in text
