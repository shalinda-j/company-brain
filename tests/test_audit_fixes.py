"""Coverage for the security/robustness audit batch: CLI delete, rate
limiting, new redact patterns, atomic writes, per-key roles, recency-aware
normalized ranking, and session close end-to-end via the API."""

from __future__ import annotations

import json
import time

import httpx
import pytest

AAA = {"Authorization": "Bearer test-key-aaa"}  # agent claude-code (admin)


# --- CLI: delete subcommand ----------------------------------------------
def _cli_with_mock(monkeypatch, handler):
    import brain.cli as cli

    monkeypatch.setattr(cli, "KEY", "test-cli-key")
    monkeypatch.setattr(
        cli,
        "_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test"),
    )
    return cli


def test_cli_delete(monkeypatch, capsys):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["project"] = request.url.params.get("project")
        return httpx.Response(200, json={"deleted": "abc123"})

    cli = _cli_with_mock(monkeypatch, handler)
    assert cli.main(["delete", "abc123", "--project", "p"]) == 0
    assert seen == {"method": "DELETE", "path": "/delete/abc123", "project": "p"}
    assert "abc123" in capsys.readouterr().out


def test_cli_delete_missing_returns_error(monkeypatch, capsys):
    cli = _cli_with_mock(
        monkeypatch, lambda req: httpx.Response(404, json={"detail": "Not found"})
    )
    assert cli.main(["delete", "nope"]) == 1
    assert "error 404" in capsys.readouterr().err


# --- rate limiting --------------------------------------------------------
def test_rate_limit_middleware_present_and_429(client):
    from slowapi.middleware import SlowAPIMiddleware

    import api.server as srv

    assert any(m.cls is SlowAPIMiddleware for m in srv.app.user_middleware)
    srv.limiter.reset()
    try:
        # Default limit is 120/minute; unauthenticated requests share the
        # test client's IP bucket, so the 121st must be throttled.
        codes = [client.get("/health").status_code for _ in range(125)]
        assert codes[0] == 200
        assert 429 in codes
        first_429 = codes.index(429)
        assert all(c == 200 for c in codes[:first_429])
    finally:
        srv.limiter.reset()  # don't leak an exhausted bucket into other tests


# --- redaction: new secret patterns ----------------------------------------
NEW_PATTERNS = {
    "private_key_block": (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA7bq0\nmultilinebody999\n"
        "-----END RSA PRIVATE KEY-----"
    ),
    "github_token": "ghp_" + "Ab1" * 12,
    "slack_token": "xoxb-1234567890-abcdEFGHijkl",
    "google_api_key": "AIza" + "B" * 35,
    "stripe_live_key": "sk_live_" + "a1B2" * 6,
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
}


@pytest.mark.parametrize("kind", sorted(NEW_PATTERNS))
def test_redact_new_patterns(kind):
    from brain import redact

    secret = NEW_PATTERNS[kind]
    text = f"before {secret} after"
    assert kind in {f["type"] for f in redact.scan(text)}
    out, findings = redact.redact(text)
    assert secret not in out
    assert f"[REDACTED:{kind}]" in out
    # Findings carry only a masked preview, never the secret itself.
    assert all(secret not in json.dumps(f) for f in findings)


def test_redact_on_save_default_scrubs_secrets(brain):
    # config.py flip (audit item 14): REDACT_ON_SAVE defaults to True.
    from brain.config import config

    assert config.redact_on_save is True
    note = brain.save(content="aws key AKIAIOSFODNN7EXAMPLE here", title="leak")
    assert note["pii_findings"]
    stored = brain.get(note["id"])
    assert "AKIAIOSFODNN7EXAMPLE" not in stored["content"]
    assert "[REDACTED:aws_access_key]" in stored["content"]


# --- atomic writes ----------------------------------------------------------
def test_atomic_write_uses_os_replace(tmp_path, monkeypatch):
    import os

    from brain import vault

    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(vault.os, "replace", spy)
    target = tmp_path / "data.json"
    vault.atomic_write(target, "payload")
    assert target.read_text(encoding="utf-8") == "payload"
    assert calls and str(calls[0][1]) == str(target)
    assert not target.with_name("data.json.tmp").exists()


def test_facts_save_survives_crash_mid_write(brain, monkeypatch):
    from brain import facts, vault

    facts._save("p", [{"subject": "s", "value": "old"}])

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(vault.os, "replace", boom)
    with pytest.raises(OSError):
        facts._save("p", [{"subject": "s", "value": "new"}])
    # The target file is untouched: a crash mid-write never corrupts it.
    data = json.loads(facts._path("p").read_text(encoding="utf-8"))
    assert data == [{"subject": "s", "value": "old"}]


# --- per-key roles -----------------------------------------------------------
def test_role_enforcement(client, monkeypatch):
    import brain.security as sec

    keys = dict(sec._API_KEYS)
    keys["read-key"] = ("reader", "read")
    keys["write-key"] = ("writer", "write")
    monkeypatch.setattr(sec, "_API_KEYS", keys)
    read = {"Authorization": "Bearer read-key"}
    write = {"Authorization": "Bearer write-key"}

    # read role: read endpoints work, write/admin endpoints are 403.
    assert client.get("/recent", headers=read).status_code == 200
    assert client.post("/save", json={"content": "x"}, headers=read).status_code == 403
    assert client.delete("/delete/whatever", headers=read).status_code == 403

    # write role: write works, admin is still 403.
    r = client.post("/save", json={"content": "hello from writer"}, headers=write)
    assert r.status_code == 200 and r.json()["agent"] == "writer"
    assert client.delete("/delete/whatever", headers=write).status_code == 403

    # admin key reaches the handler (404 for a missing note, not 403).
    assert client.delete("/delete/missing", headers=AAA).status_code == 404


# --- ranking: normalization + recency decay ---------------------------------
def test_search_relevance_normalized_to_unit_range(brain):
    brain.save(content="qdrant vector database powers the search", title="a")
    brain.save(content="fastapi serves the http api", title="b")
    hits = brain.search("vector database search", limit=5)
    assert hits
    scores = [h["score"] for h in hits]
    # Raw RRF scores max out around 0.033; search must rescale so the top
    # relevance is 1.0 and boosts can't dwarf it.
    assert max(scores) == pytest.approx(1.0)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_final_rank_boost_does_not_dwarf_relevance(brain):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    relevant = {
        "note_id": "rel",
        "score": 1.0,
        "usefulness": 0,
        "access_count": 0,
        "importance": 1,
        "updated": "2020-01-01T00:00:00Z",
    }
    boosted = {
        "note_id": "boost",
        "score": 0.5,
        "usefulness": 10,
        "access_count": 10,
        "importance": 1,
        "updated": now,
    }
    ranked = brain._final_rank([dict(boosted), dict(relevant)])
    assert ranked[0]["note_id"] == "rel"


def test_final_rank_recency_decay(brain):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fresh = {
        "note_id": "fresh",
        "score": 0.5,
        "usefulness": 0,
        "access_count": 0,
        "importance": 1,
        "updated": now,
    }
    stale = dict(fresh, note_id="stale", updated="2020-01-01T00:00:00Z")
    ranked = brain._final_rank([dict(stale), dict(fresh)])
    assert ranked[0]["note_id"] == "fresh"
    assert ranked[0]["final_score"] > ranked[1]["final_score"]


# --- session close end-to-end via the API ------------------------------------
def test_session_close_endpoint(client):
    for i in range(3):
        r = client.post(
            "/checkpoint",
            json={"note": f"step {i}", "session": "s9", "project": "p"},
            headers=AAA,
        )
        assert r.status_code == 200
    r = client.post("/session/close", json={"project": "p", "session": "s9"}, headers=AAA)
    assert r.status_code == 200
    d = r.json()
    assert d["checkpoints"] == 3 and d["summary_note_id"]
    note = client.get(
        f"/get/{d['summary_note_id']}", params={"project": "p"}, headers=AAA
    ).json()
    assert "session-summary" in note["tags"]
    assert "step 2" in note["content"]
    # Closing again finds a closed journal: nothing to summarize.
    r2 = client.post("/session/close", json={"project": "p", "session": "s9"}, headers=AAA)
    assert r2.json() == {"summary_note_id": None, "checkpoints": 0}


def test_session_close_validation(client):
    assert (
        client.post("/session/close", json={"project": "p"}, headers=AAA).status_code == 422
    )
