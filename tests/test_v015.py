"""v0.0.1.5: always-applied directives (pinned tier), recall transparency
(included/dropped layers + guaranteed slots), and per-agent identity/facts
scoping (SOUL/blocks/preferences overlays + agent-scoped fact reconciliation)."""

from __future__ import annotations

AAA = {"Authorization": "Bearer test-key-aaa"}  # agent claude-code


# --- 1. pinned / directive tier ----------------------------------------
def test_directive_always_in_recall_regardless_of_query(brain):
    brain.add_directive("never deploy on Fridays", project="p")
    rc = brain.recall("what color is the sky", project="p")  # semantically unrelated
    assert any("never deploy on Fridays" in d["text"] for d in rc["directives"])
    assert "directives" in rc["included_layers"]
    assert "never deploy on Fridays" in rc["context"]


def test_pin_and_unpin_normal_note(brain):
    n = brain.save("rotate API keys quarterly", title="sec", project="p")
    assert not any(d["id"] == n["id"] for d in brain.directives(project="p"))
    brain.set_pinned(n["id"], True, project="p")
    assert any(d["id"] == n["id"] for d in brain.directives(project="p"))
    rc = brain.recall("totally unrelated query about cats", project="p")
    assert any(d["id"] == n["id"] for d in rc["directives"])
    brain.set_pinned(n["id"], False, project="p")
    assert not any(d["id"] == n["id"] for d in brain.directives(project="p"))


# --- 2. recall transparency --------------------------------------------
def test_recall_reports_dropped_layers(brain):
    for i in range(10):
        brain.save(
            f"memory {i} about pipelines and deployment stages number {i}",
            title=f"m{i}",
            project="p",
            allow_duplicate=True,
        )
    rc = brain.recall("pipeline deployment stages", project="p", token_budget=60)
    assert "included_layers" in rc and "dropped_layers" in rc
    assert "soul" in rc["included_layers"]  # guaranteed layer kept
    assert "memories" in rc["dropped_layers"]  # signalled, not silently gone


def test_facts_layer_guaranteed_over_memories(brain):
    brain.save("we use [[Postgres]] for storage", title="db", project="p")
    brain.add_fact("Postgres", "the primary datastore", project="p")
    for i in range(8):
        brain.save(f"filler memory {i} postgres", title=f"f{i}", project="p", allow_duplicate=True)
    rc = brain.recall("Postgres", project="p", token_budget=80)
    # facts is a guaranteed layer; it must be present even under a tight budget.
    assert "facts" in rc["included_layers"]


# --- 3. per-agent SOUL / preferences / blocks --------------------------
def test_per_agent_soul_isolation(brain):
    brain.set_soul("# SOUL\n\nShared identity.", project="p")
    brain.learn_principle("Agent A prefers Rust", project="p", agent="agentA")
    rc_a = brain.recall("anything", project="p", agent="agentA")
    rc_b = brain.recall("anything", project="p", agent="agentB")
    assert "Agent A prefers Rust" in rc_a["context"]
    assert "Agent A prefers Rust" not in rc_b["context"]
    assert "Shared identity" in rc_a["context"] and "Shared identity" in rc_b["context"]


def test_per_agent_preferences_overlay(brain):
    brain.set_preference("lang", "Sinhala", project="p")
    brain.set_preference("editor", "vim", project="p", agent="agentA")
    rc_a = brain.recall("x", project="p", agent="agentA")
    rc_b = brain.recall("x", project="p", agent="agentB")
    assert "lang: Sinhala" in rc_a["context"] and "editor: vim" in rc_a["context"]
    assert "editor: vim" not in rc_b["context"] and "lang: Sinhala" in rc_b["context"]


def test_per_agent_blocks_override(brain):
    brain.set_block("human", "shared human block", project="p")
    brain.set_block("human", "agentA human block", project="p", agent="agentA")
    assert brain.list_blocks(project="p", agent="agentA")["human"] == "agentA human block"
    assert brain.list_blocks(project="p")["human"] == "shared human block"


# --- 4. per-agent fact reconciliation ----------------------------------
def test_facts_not_clobbered_across_agents(brain):
    brain.add_fact("db", "postgres", project="p", agent="agentA")
    brain.add_fact("db", "mysql", project="p", agent="agentB")
    vals = {f["value"] for f in brain.facts(subject="db", project="p")}
    assert vals == {"postgres", "mysql"}  # both survive — no cross-agent last-write-wins

    brain.add_fact("db", "sqlite", project="p", agent="agentA")  # supersedes only A's
    cur_a = [f for f in brain.facts(subject="db", project="p") if f["agent"] == "agentA"]
    assert len(cur_a) == 1 and cur_a[0]["value"] == "sqlite"

    contras = brain.doctor(project="p")["fact_contradictions"]
    db_conflict = [c for c in contras if c["subject"] == "db"]
    assert db_conflict and set(db_conflict[0]["agents"]) == {"agentA", "agentB"}


# --- 5. API smoke -------------------------------------------------------
def test_api_directives_pin_and_agent_scope(client):
    d = client.post("/directives", json={"text": "never deploy on Fridays"}, headers=AAA)
    assert d.status_code == 200
    lst = client.get("/directives", headers=AAA).json()["directives"]
    assert any("never deploy" in x["text"] for x in lst)

    rc = client.post("/recall", json={"query": "something unrelated"}, headers=AAA).json()
    assert "directives" in rc["included_layers"]
    assert "never deploy on Fridays" in rc["context"]
    assert "dropped_layers" in rc

    s = client.post("/save", json={"content": "pin me", "title": "p"}, headers=AAA).json()
    pinned = client.post("/pin", json={"note_id": s["id"], "pinned": True}, headers=AAA)
    assert pinned.status_code == 200
    miss = client.post("/pin", json={"note_id": "missing"}, headers=AAA)
    assert miss.status_code == 404

    r = client.post(
        "/soul", json={"text": "# SOUL\n\npersonal note", "agent_scope": True}, headers=AAA
    )
    assert r.status_code == 200
