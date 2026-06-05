"""v0.0.1.6: real-time session/checkpoint layer (crash recovery)."""

from __future__ import annotations

AAA = {"Authorization": "Bearer test-key-aaa"}


def test_checkpoint_and_resume(brain):
    brain.checkpoint(
        "editing parser", session_id="s1", files=["parser.py"], next_step="add tests", project="p"
    )
    brain.checkpoint(
        "wrote tests", session_id="s1", files=["test_parser.py"], git_ref="abc123", project="p"
    )
    r = brain.resume(session_id="s1", project="p")
    assert r["found"] and r["session"] == "s1"
    assert r["latest"]["note"] == "wrote tests"
    assert r["latest"]["git_ref"] == "abc123"
    assert len(r["recent"]) == 2  # newest first
    assert r["recent"][0]["note"] == "wrote tests"


def test_resume_latest_session_when_unspecified(brain):
    brain.checkpoint("old work", session_id="old", project="p")
    brain.checkpoint("current work", session_id="new", project="p")
    r = brain.resume(project="p")  # no session -> most recent
    assert r["found"] and r["latest"]["note"] == "current work"


def test_sessions_list(brain):
    brain.checkpoint("a", session_id="alpha", project="p")
    brain.checkpoint("b", session_id="beta", project="p")
    names = {s["session"] for s in brain.sessions(project="p")}
    assert {"alpha", "beta"} <= names


def test_checkpoints_do_not_pollute_recall(brain):
    brain.save("real semantic memory about pipelines", title="m", project="p")
    for i in range(5):
        brain.checkpoint(f"step {i}", session_id="s", project="p")
    # checkpoints live in _sessions (reserved) -> never indexed as notes
    titles = [r["title"] for r in brain.recent(50, project="p")]
    assert not any("step" in t for t in titles)


def test_checkpoint_redaction(brain, monkeypatch):
    from brain.config import config

    monkeypatch.setattr(config, "redact_on_save", True)
    r = brain.checkpoint("deploying with key AKIAIOSFODNN7EXAMPLE", session_id="s", project="p")
    assert "AKIAIOSFODNN7EXAMPLE" not in r["note"] and "REDACTED" in r["note"]


def test_api_checkpoint_resume_sessions(client):
    cp = client.post(
        "/checkpoint",
        json={"note": "api step one", "session": "s1", "files": ["a.py"], "next": "step two"},
        headers=AAA,
    )
    assert cp.status_code == 200 and cp.json()["session"] == "s1"
    r = client.get("/resume", params={"session": "s1"}, headers=AAA).json()
    assert r["found"] and r["latest"]["note"] == "api step one"
    sess = client.get("/sessions", headers=AAA).json()["sessions"]
    assert any(s["session"] == "s1" for s in sess)
