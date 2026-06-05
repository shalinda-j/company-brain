"""Tests for the v3 multi-layer memory features: entities/graph, document
relationships, SOUL, preferences, ontology, multi-layer recall (with dynamic
weights + token budget), dreaming, heartbeat tick, and access-based learning."""

from __future__ import annotations


# --- entities & graph ---------------------------------------------------
def test_entity_extraction_and_graph(brain):
    brain.save(
        content="Working with [[Qdrant]] and #fastapi for the [[avedit]] tool",
        title="stack",
        project="p",
    )
    ents = {e["entity"].lower() for e in brain.entities(project="p")}
    assert {"qdrant", "fastapi", "avedit"} <= ents
    notes = brain.entity_notes("Qdrant", project="p")
    assert notes and notes[0]["title"] == "stack"
    nb = {n["entity"].lower() for n in brain.entity_neighbors("Qdrant", project="p")}
    assert "fastapi" in nb and "avedit" in nb


def test_related_by_shared_entities(brain):
    a = brain.save(content="[[avedit]] pipeline design notes", title="A", project="p")
    b = brain.save(content="[[avedit]] export stage details", title="B", project="p")
    rel = brain.related(a["id"], project="p")
    assert any(r["note_id"] == b["id"] for r in rel)


# --- SOUL ---------------------------------------------------------------
def test_soul_default_and_learn(brain):
    assert "SOUL" in brain.get_soul(project="p")
    brain.learn_principle("Always prefer Qdrant for vector search", project="p")
    assert "Always prefer Qdrant" in brain.get_soul(project="p")


def test_soul_set(brain):
    brain.set_soul("# SOUL\n\nI am the avedit assistant.", project="p")
    assert "avedit assistant" in brain.get_soul(project="p")


# --- preferences --------------------------------------------------------
def test_preferences(brain):
    brain.set_preference("language", "Sinhala", project="p")
    brain.set_preference("tone", "concise", project="p")
    prefs = brain.get_preferences(project="p")
    assert prefs["language"] == "Sinhala" and prefs["tone"] == "concise"


# --- multi-layer recall -------------------------------------------------
def test_recall_bundles_layers(brain):
    brain.set_soul("# SOUL\n\nI build avedit.", project="p")
    brain.set_preference("language", "Sinhala", project="p")
    brain.save(
        content="avedit uses a six-stage video pipeline",
        title="pipeline",
        category="knowledge",
        project="p",
    )
    bundle = brain.recall("tell me about the avedit pipeline", project="p")
    assert "I build avedit" in bundle["context"]  # soul present
    assert "language" in bundle["context"]  # preferences present
    assert bundle["memories"]  # memories layer
    assert bundle["approx_tokens"] <= brain_recall_budget(brain)


def brain_recall_budget(brain):
    from brain.config import config

    return config.recall_token_budget


def test_recall_dynamic_weighting(brain):
    brain.save(
        content="To deploy: run install.sh then docker compose up",
        title="deploy guide",
        category="procedure",
        project="p",
    )
    brain.save(content="Random unrelated fact about cats", title="cats", project="p")
    how = brain.recall("how to deploy the service", project="p")
    normal = brain.recall("tell me a fact", project="p")
    assert how["priority_order"].index("procedures") < how["priority_order"].index("memories")
    assert normal["priority_order"].index("memories") < normal["priority_order"].index("procedures")


def test_recall_token_budget_respected(brain):
    for i in range(20):
        brain.save(
            content=f"Memory number {i} about the avedit project pipeline stage {i}",
            title=f"m{i}",
            project="p",
            allow_duplicate=True,
        )
    bundle = brain.recall("avedit pipeline", project="p", token_budget=300)
    assert bundle["approx_tokens"] <= 300


# --- ontology -----------------------------------------------------------
def test_ontology_tag_expansion(brain):
    brain.set_ontology("python", "programming")
    brain.save(content="Django ORM stuff here", title="django", tags=["python"], project="p")
    hits = brain.search("Django stuff", tag="programming", project="p")
    assert any(h["title"] == "django" for h in hits)


# --- autonomous learning (access) --------------------------------------
def test_access_increments_usefulness_signal(brain):
    n = brain.save(content="frequently accessed memory", title="hot", project="p")
    brain.get(n["id"], project="p")
    brain.get(n["id"], project="p")
    again = brain.get(n["id"], project="p", track=False)
    assert again["access_count"] >= 2


# --- dreaming -----------------------------------------------------------
def test_dream_creates_digests(brain, monkeypatch):
    from brain.config import config

    monkeypatch.setattr(config, "dream_relate_threshold", 0.3)
    brain.save(
        content="Deploy avedit with Docker and Caddy for TLS termination",
        title="deploy A",
        category="knowledge",
        project="p",
    )
    brain.save(
        content="Deploy avedit using Docker plus Caddy to handle TLS",
        title="deploy B",
        category="knowledge",
        project="p",
        allow_duplicate=True,
    )
    res = brain.dream(project="p")
    assert res["digests_created"] >= 1
    digests = [r for r in brain.recent(50, project="p") if "dream-digest" in r["tags"]]
    assert digests


# --- heartbeat tick -----------------------------------------------------
def test_tick_decays_unused(brain):
    n = brain.save(
        content="a memory that will be boosted then left unused", title="decay me", project="p"
    )
    brain.feedback(n["id"], useful=True, project="p")
    brain.feedback(n["id"], useful=True, project="p")  # usefulness = 2, access = 0
    brain.tick(project="p")
    after = brain.get(n["id"], project="p", track=False)
    assert after["usefulness"] == 1  # decayed by one step


# --- API smoke for new endpoints ---------------------------------------
def test_api_recall_and_soul(client):
    h = {"Authorization": "Bearer test-key-aaa"}
    client.post(
        "/save", json={"content": "avedit pipeline info", "title": "p", "project": "x"}, headers=h
    )
    client.post("/soul", json={"text": "# SOUL\n\nI build avedit.", "project": "x"}, headers=h)
    r = client.post("/recall", json={"query": "avedit pipeline", "project": "x"}, headers=h)
    assert r.status_code == 200
    assert "avedit" in r.json()["context"].lower()
    s = client.get("/soul", params={"project": "x"}, headers=h)
    assert "avedit" in s.json()["soul"]


def test_api_entities(client):
    h = {"Authorization": "Bearer test-key-aaa"}
    client.post(
        "/save", json={"content": "using [[Qdrant]] here", "title": "q", "project": "x"}, headers=h
    )
    r = client.get("/entities", params={"project": "x"}, headers=h)
    assert any(e["entity"] == "Qdrant" for e in r.json()["entities"])
