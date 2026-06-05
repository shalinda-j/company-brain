"""v0.0.1.3 feature tests: hybrid search, bi-temporal facts, PII redaction,
core memory blocks, entity resolution, communities + multi-hop, importance,
archival, doctor, export/import, file ingestion, per-user scoping, metrics,
sleep cycle, the eval harness, and the new API endpoints."""

from __future__ import annotations

AAA = {"Authorization": "Bearer test-key-aaa"}


# --- hybrid search ------------------------------------------------------
def test_hybrid_surfaces_exact_keyword(brain):
    target = brain.save(
        content="The quarterly memo references project Zorblax9000 milestones.",
        title="memo",
        project="p",
    )
    brain.save(
        content="Notes about cats, dogs, gardening and the weather today.",
        title="noise",
        project="p",
        allow_duplicate=True,
    )
    hits = brain.search("Zorblax9000", project="p", limit=3)
    assert hits and hits[0]["note_id"] == target["id"]


def test_hybrid_can_be_disabled(brain):
    brain.save(content="alpha beta gamma delta", title="g", project="p")
    assert isinstance(brain.search("alpha", project="p", hybrid_search=False), list)


# --- PII / secret redaction --------------------------------------------
def test_pii_findings_reported_on_save(brain):
    r = brain.save(
        content="deploy key AKIAIOSFODNN7EXAMPLE and contact me@example.com",
        title="leak",
        project="p",
    )
    types = {f["type"] for f in r["pii_findings"]}
    assert "aws_access_key" in types and "email" in types


def test_redact_on_save_scrubs_content(brain, monkeypatch):
    from brain.config import config

    monkeypatch.setattr(config, "redact_on_save", True)
    r = brain.save(content="token AKIAIOSFODNN7EXAMPLE here", title="r", project="p")
    stored = brain.get(r["id"], project="p")["content"]
    assert "AKIAIOSFODNN7EXAMPLE" not in stored and "REDACTED" in stored


# --- bi-temporal facts --------------------------------------------------
def test_fact_invalidation_and_history(brain):
    brain.add_fact("billing", "monthly", project="p")
    second = brain.add_fact("billing", "annual", project="p")
    assert second["invalidated"]  # superseded the prior fact
    current = brain.facts(subject="billing", project="p")
    assert len(current) == 1 and current[0]["value"] == "annual"
    hist = brain.fact_history("billing", project="p")
    assert len(hist) == 2
    assert brain.facts(project="p")  # contradiction-free current set


# --- core memory blocks -------------------------------------------------
def test_blocks_set_get_append_cap_and_recall(brain):
    brain.set_block("human", "User is Shalinda; prefers Sinhala.", project="p")
    assert "Shalinda" in brain.get_block("human", project="p")
    brain.append_block("human", "Based in Sri Lanka.", project="p")
    assert "Sri Lanka" in brain.get_block("human", project="p")
    assert "human" in brain.list_blocks(project="p")
    from brain.config import config

    brain.set_block("big", "x" * (config.block_char_limit + 500), project="p")
    assert len(brain.get_block("big", project="p")) <= config.block_char_limit + 32
    rc = brain.recall("tell me about the user", project="p")
    assert "Shalinda" in rc["context"]


# --- entity resolution --------------------------------------------------
def test_alias_merges_entities(brain):
    brain.set_alias("qdrant db", "Qdrant")
    brain.save(content="we use [[qdrant db]] for vectors", title="a", project="p")
    brain.save(content="more on [[Qdrant]] indexing", title="b", project="p")
    ents = brain.entities(project="p")
    qdrant = [e for e in ents if e["entity"] == "Qdrant"]
    assert len(qdrant) == 1 and qdrant[0]["mentions"] == 2
    assert not any(e["entity"].lower() == "qdrant db" for e in ents)


# --- communities + multi-hop -------------------------------------------
def test_communities_two_clusters(brain):
    brain.save(content="link [[Alpha]] and [[Beta]] together", title="ab", project="p")
    brain.save(
        content="more [[Beta]] with [[Alpha]]", title="ab2", project="p", allow_duplicate=True
    )
    brain.save(content="separately [[Xray]] and [[Yankee]]", title="xy", project="p")
    brain.save(
        content="again [[Yankee]] with [[Xray]]", title="xy2", project="p", allow_duplicate=True
    )
    comms = brain.communities(project="p")
    assert len(comms) == 2
    assert all(len(c["members"]) == 2 for c in comms)


def test_multihop_reaches_depth_two(brain):
    brain.save(content="chain [[Aaa]] to [[Bbb]]", title="c1", project="p")
    brain.save(content="chain [[Bbb]] to [[Ccc]]", title="c2", project="p")
    reach1 = {x["entity"] for x in brain.entity_multihop("Aaa", depth=1, project="p")}
    reach2 = {x["entity"] for x in brain.entity_multihop("Aaa", depth=2, project="p")}
    assert "Bbb" in reach1 and "Ccc" not in reach1
    assert "Ccc" in reach2


# --- importance ---------------------------------------------------------
def test_importance_heuristic_and_override(brain):
    plain = brain.save(content="short note", title="s", project="p")
    assert plain["importance"] == 1
    rich = brain.save(
        content="x" * 500 + " with [[Entity]]", title="r", category="knowledge", project="p"
    )
    assert rich["importance"] >= 3
    forced = brain.save(content="whatever", title="f", project="p", importance=5)
    assert forced["importance"] == 5


# --- archival -----------------------------------------------------------
def test_archive_excludes_from_default_views(brain):
    n = brain.save(content="archivable memory about owls", title="o", project="p")
    brain.set_archived(n["id"], True, project="p")
    assert n["id"] not in [r["id"] for r in brain.recent(50, project="p")]
    assert n["id"] in [r["id"] for r in brain.recent(50, project="p", include_archived=True)]
    default_hits = [h["note_id"] for h in brain.search("owls", project="p")]
    incl_hits = [h["note_id"] for h in brain.search("owls", project="p", include_archived=True)]
    assert n["id"] not in default_hits and n["id"] in incl_hits


# --- doctor -------------------------------------------------------------
def test_doctor_detects_duplicates_and_pii(brain):
    brain.save(content="identical content for dup detection", title="d1", project="p")
    brain.save(
        content="identical content for dup detection", title="d2", project="p", allow_duplicate=True
    )
    brain.save(content="secret AKIAIOSFODNN7EXAMPLE inside", title="leak", project="p")
    report = brain.doctor(project="p")
    s = report["summary"]
    for key in (
        "duplicate_pairs",
        "stale",
        "orphan_entities",
        "oversized_blocks",
        "pii_notes",
        "fact_contradictions",
    ):
        assert key in s
    assert s["duplicate_pairs"] >= 1
    assert s["pii_notes"] >= 1


# --- export / import ----------------------------------------------------
def test_export_import_round_trip(brain):
    brain.save(content="exportable one", title="e1", project="exp")
    brain.save(content="exportable two", title="e2", project="exp")
    brain.set_soul("I am the export test brain.", project="exp")
    brain.set_block("human", "user prefers exports", project="exp")
    brain.set_preference("tone", "direct", project="exp")
    brain.add_fact("status", "active", project="exp")
    bundle = brain.export(project="exp")
    assert len(bundle["notes"]) == 2

    res = brain.import_bundle(bundle, project="exp2")
    assert res["imported_notes"] == 2
    from brain import vault

    assert sum(1 for _ in vault.iter_notes("exp2")) == 2
    assert "export test brain" in brain.get_soul(project="exp2")
    assert "human" in brain.list_blocks(project="exp2")
    assert brain.get_preferences(project="exp2").get("tone") == "direct"
    assert brain.facts(subject="status", project="exp2")[0]["value"] == "active"


# --- file ingestion -----------------------------------------------------
def test_ingest_file(brain, tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("DigitalOcean deployment runbook with Caddy TLS notes.", encoding="utf-8")
    r = brain.ingest_file(f, project="p")
    assert r["category"] == "knowledge" and r["title"] == "doc.txt"
    assert brain.search("deployment runbook", project="p")


# --- per-user scoping ---------------------------------------------------
def test_per_user_search_filter(brain):
    brain.save(content="u1 private grocery list", title="u1n", project="p", user="u1")
    brain.save(content="u2 private grocery list", title="u2n", project="p", user="u2")
    hits = brain.search("grocery list", project="p", user="u1")
    assert hits and all(
        brain.get(h["note_id"], project="p", track=False)["user"] == "u1" for h in hits
    )


# --- metrics ------------------------------------------------------------
def test_metrics_counters(brain):
    brain.save(content="metric note", title="m", project="p")
    brain.search("metric", project="p")
    m = brain.metrics()
    assert m.get("save", 0) >= 1 and m.get("search", 0) >= 1


# --- sleep cycle --------------------------------------------------------
def test_sleep_cycle_archives_stale(brain, monkeypatch):
    from brain.config import config

    monkeypatch.setattr(config, "sleep_archive", True)
    brain.save(content="trivial stale memory nobody reads", title="stale", project="p")
    res = brain.sleep_cycle(project="p")
    assert "remaining_issues" in res
    assert res["archived"] >= 1


# --- eval harness -------------------------------------------------------
def test_eval_harness_offline(brain):
    a = brain.save(
        content="the avedit pipeline removes silence and upscales", title="a", project="p"
    )
    brain.save(
        content="unrelated content about taxes", title="b", project="p", allow_duplicate=True
    )
    from brain import evaluate

    dataset = [{"query": "avedit silence upscale pipeline", "expected": [a["id"]], "project": "p"}]
    metrics = evaluate.run(lambda q, pr: brain.search(q, project=pr or "p"), dataset, k=5)
    assert metrics["cases"] == 1
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] > 0


# --- API smoke for new endpoints ---------------------------------------
def test_api_facts_blocks_doctor_metrics(client):
    r = client.post("/facts", json={"subject": "plan", "value": "pro"}, headers=AAA)
    assert r.status_code == 200
    r = client.get("/facts", params={"subject": "plan"}, headers=AAA)
    assert r.status_code == 200 and r.json()["facts"][0]["value"] == "pro"
    assert client.get("/facts/plan/history", headers=AAA).status_code == 200

    assert (
        client.post("/blocks", json={"name": "human", "text": "hi"}, headers=AAA).status_code == 200
    )
    assert "human" in client.get("/blocks", headers=AAA).json()["blocks"]
    assert client.get("/block/human", headers=AAA).status_code == 200

    assert "summary" in client.get("/doctor", headers=AAA).json()
    assert "metrics" in client.get("/metrics", headers=AAA).json()
    assert "communities" in client.get("/communities", headers=AAA).json()


def test_api_archive_export_import(client):
    s = client.post(
        "/save", json={"content": "api archive target", "title": "t"}, headers=AAA
    ).json()
    arch = client.post("/archive", json={"note_id": s["id"], "archived": True}, headers=AAA)
    assert arch.status_code == 200
    miss = client.post("/archive", json={"note_id": "missing"}, headers=AAA)
    assert miss.status_code == 404

    bundle = client.get("/export", headers=AAA).json()
    assert "notes" in bundle
    r = client.post("/import", json={"bundle": bundle, "project": "imp"}, headers=AAA)
    assert r.status_code == 200 and r.json()["imported_notes"] >= 1

    mh = client.get("/entities/anything/multihop", params={"depth": 2}, headers=AAA)
    assert mh.status_code == 200
    al = client.post("/alias", json={"alias": "k8s", "canonical": "Kubernetes"}, headers=AAA)
    assert al.status_code == 200
    assert client.post("/maintenance/sleep", headers=AAA).status_code == 200
