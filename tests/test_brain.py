"""Core Brain pipeline tests (v2): save, search, get, recent, activity,
reindex, delete, projects, dedup/safe-save, feedback re-ranking, consolidation,
ingest, and dimension-mismatch auto-recovery."""

from __future__ import annotations


def _seed(brain, project="default"):
    a = brain.save(
        content="DigitalOcean droplet eke Qdrant + FastAPI use karala company brain "
        "ekak hadanawa. Security walata API key auth.",
        title="Company brain architecture",
        category="knowledge",
        tags=["infra"],
        agent="claude-code",
        project=project,
    )
    b = brain.save(
        content="avedit kiyanne Python video editing pipeline ekak. Silence removal, "
        "color correction, AI upscaling.",
        title="avedit pipeline",
        category="notes",
        tags=["avedit"],
        agent="cursor",
        project=project,
    )
    return a, b


def test_save_indexes_chunks(brain):
    note = brain.save(content="hello world memory", title="hello")
    assert note["id"]
    assert note["chunks"] >= 1
    assert note["agent"] == "default"
    assert note["project"] == "default"
    assert note["duplicate"] is False


def test_search_finds_relevant_note(brain):
    _seed(brain)
    hits = brain.search("how to host a brain on a server with auth", limit=3)
    assert "Company brain architecture" in [h["title"] for h in hits]


def test_search_filtered_by_agent(brain):
    _seed(brain)
    hits = brain.search("video editing", limit=5, agent="cursor")
    assert hits and all(h["agent"] == "cursor" for h in hits)


def test_get_and_missing(brain):
    a, _ = _seed(brain)
    assert brain.get(a["id"])["title"] == "Company brain architecture"
    assert brain.get("nope") is None


def test_recent_newest_first(brain):
    _seed(brain)
    rec = brain.recent(10)
    updated = [r["updated"] for r in rec]
    assert updated == sorted(updated, reverse=True)


def test_activity_per_agent(brain):
    _seed(brain)
    items = brain.activity(agent="cursor", n=20)
    assert items and all(i["agent"] == "cursor" for i in items)


def test_searches_logged(brain):
    _seed(brain)
    brain.search("anything", limit=2, searched_by="claude-code")
    assert any(r["category"] == "activity" for r in brain.recent(50))


def test_reindex_rebuilds(brain):
    _seed(brain)
    stats = brain.reindex()
    assert stats["notes"] >= 2 and stats["vectors"] >= 2
    assert brain.search("brain architecture", limit=2)


def test_delete(brain):
    a, b = _seed(brain)
    assert brain.delete(b["id"]) is True
    assert brain.get(b["id"]) is None
    assert brain.delete("missing") is False


def test_unicode_sinhala(brain):
    note = brain.save(content="ආයුබෝවන් — සිංහල memory එකකි.", title="සිංහල", category="notes")
    assert "සිංහල" in brain.get(note["id"])["content"]


# --- v2 features --------------------------------------------------------
def test_projects_are_isolated(brain):
    brain.save(content="avedit pipeline details", title="avedit", project="avedit")
    brain.save(content="wedding vendor marketplace", title="weddinghub", project="weddinghub")
    # Search in avedit must not return weddinghub content.
    av = brain.search("wedding marketplace", limit=5, project="avedit")
    assert all("wedding" not in h["title"] for h in av)
    wh = brain.search("wedding marketplace", limit=5, project="weddinghub")
    assert any("weddinghub" == h["title"] for h in wh)
    names = [p["project"] for p in brain.projects()]
    assert "avedit" in names and "weddinghub" in names


def test_safe_save_dedup(brain):
    first = brain.save(content="The brain uses Qdrant for vector search.", title="stack note")
    assert first["duplicate"] is False
    dup = brain.save(content="The brain uses Qdrant for vector search.", title="stack note again")
    assert dup["duplicate"] is True
    assert dup["id"] == first["id"]
    # Only one note actually stored.
    assert sum(1 for r in brain.recent(50) if r["category"] != "activity") == 1


def test_allow_duplicate_override(brain):
    brain.save(content="exact same text here", title="one")
    second = brain.save(content="exact same text here", title="two", allow_duplicate=True)
    assert second["duplicate"] is False


def test_feedback_boosts_ranking(brain):
    a, b = _seed(brain)
    # Give the avedit note positive feedback several times.
    for _ in range(5):
        brain.feedback(b["id"], useful=True)
    res = brain.feedback(b["id"], useful=True)
    assert res["usefulness"] >= 5
    # A generic query returns results; the boosted note carries a final_score.
    hits = brain.search("pipeline tool", limit=5)
    target = [h for h in hits if h["note_id"] == b["id"]]
    assert target and target[0]["final_score"] >= target[0]["score"]


def test_feedback_missing(brain):
    assert brain.feedback("does-not-exist") is None


def test_ingest_stores_conversation(brain):
    note = brain.ingest(
        text="We decided to deploy on DigitalOcean with Caddy for TLS.", project="avedit"
    )
    assert note["category"] == "conversations"
    assert "ingested" in note["tags"]
    assert brain.search("where did we deploy", project="avedit", limit=3)


def test_consolidate_merges_duplicates(brain):
    brain.save(content="Meeting: ship the avedit MVP next week.", title="m1", tags=["mvp"])
    # Force a near-duplicate into the vault (bypass safe-save).
    brain.save(
        content="Meeting: ship the avedit MVP next week.",
        title="m2",
        tags=["plan"],
        allow_duplicate=True,
    )
    before = sum(1 for r in brain.recent(50) if r["category"] != "activity")
    assert before == 2
    res = brain.consolidate()
    assert res["removed"] >= 1
    after = sum(1 for r in brain.recent(50) if r["category"] != "activity")
    assert after < before


def test_dimension_mismatch_auto_recovery(brain, monkeypatch):
    # Seed at the current (fake) dim, then simulate switching to a model with a
    # different dimension. The store must rebuild and the vault re-index cleanly.
    _seed(brain)
    import brain.core as core
    from tests._fake import FakeEmbedder

    class BigEmbedder(FakeEmbedder):
        dim = 128

        def _vec(self, text):
            base = super()._vec(text)
            return (base + [0.0] * 128)[:128]

    monkeypatch.setattr(core, "get_embedder", lambda *a, **k: BigEmbedder())
    brain2 = core.Brain()  # same data dir; existing 96-dim collection mismatches 128
    # Should not raise; search works against the rebuilt 128-dim collection.
    hits = brain2.search("brain architecture", limit=3)
    assert isinstance(hits, list)
    assert brain2.stats()["embed_dim"] == 128
