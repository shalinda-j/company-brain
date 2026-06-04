"""End-to-end smoke test. Uses a deterministic fake embedder so it runs anywhere
(no model download). Verifies: save -> index -> search -> get -> recent ->
activity -> reindex, plus the authenticated REST API.

Run:  python tests/test_smoke.py
"""
import hashlib
import math
import os
import sys
import tempfile

# ---- configure environment BEFORE importing the app -------------------
_tmp = tempfile.mkdtemp(prefix="brain-test-")
os.environ["BRAIN_DATA_DIR"] = _tmp
os.environ["BRAIN_API_KEYS"] = "test-key-aaa:claude-code,test-key-bbb:cursor"
os.environ["LOG_SEARCHES"] = "true"
# Force embedded Qdrant (no server) for the test.
os.environ.pop("QDRANT_URL", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DIM = 96


class FakeEmbedder:
    """Deterministic bag-of-character-trigram hashing embedder (CPU, no deps)."""

    dim = DIM

    def _vec(self, text):
        v = [0.0] * DIM
        t = f"  {text.lower()} "
        for i in range(len(t) - 2):
            tri = t[i : i + 3]
            h = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
            v[h % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


# Inject the fake embedder into the brain core.
import brain.core as core  # noqa: E402

core.get_embedder = lambda *a, **k: FakeEmbedder()

from brain.core import Brain  # noqa: E402


def section(name):
    print(f"\n=== {name} ===")


def main():
    b = Brain()
    section("save")
    n1 = b.save(
        content="DigitalOcean droplet eke Qdrant + FastAPI use karala company brain ekak hadanawa. Security walata API key auth.",
        title="Company brain architecture",
        category="knowledge",
        tags=["infra", "brain"],
        agent="claude-code",
    )
    n2 = b.save(
        content="avedit kiyanne Python video editing pipeline ekak. Silence removal, color correction, AI upscaling.",
        title="avedit pipeline",
        category="notes",
        tags=["avedit", "python"],
        agent="cursor",
    )
    b.save(
        content="Chicken curry recipe with coconut milk and curry leaves.",
        title="Curry recipe",
        category="notes",
        tags=["food"],
        agent="claude-code",
    )
    print("saved:", n1["id"], n2["id"])
    assert n1["chunks"] >= 1

    section("search (should surface the brain architecture note)")
    hits = b.search("how to host a brain on a server with auth", limit=3, searched_by="claude-code")
    for h in hits:
        print(f"  {h['score']:.3f}  {h['title']}  (by {h['agent']})")
    titles = [h["title"] for h in hits]
    assert "Company brain architecture" in titles, "expected architecture note in top hits"

    section("search filtered by agent=cursor")
    hits2 = b.search("video editing", limit=5, agent="cursor", searched_by="claude-code")
    print("  cursor-only titles:", [h["title"] for h in hits2])
    assert all(h["agent"] == "cursor" for h in hits2)

    section("get")
    got = b.get(n1["id"])
    assert got and got["title"] == "Company brain architecture"
    print("  got:", got["title"])

    section("recent")
    rec = b.recent(5)
    print("  recent titles:", [r["title"] for r in rec][:5])
    assert len(rec) >= 3

    section("activity (multi-agent visibility)")
    act_cc = b.activity(agent="claude-code", n=10)
    act_cur = b.activity(agent="cursor", n=10)
    print("  claude-code did:", [a["title"] for a in act_cc])
    print("  cursor did:", [a["title"] for a in act_cur])
    assert any(a["agent"] == "cursor" for a in act_cur)

    section("search-logging (queries become memories)")
    search_notes = [r for r in b.recent(50) if r["category"] == "activity"]
    print("  logged searches:", len(search_notes))
    assert len(search_notes) >= 2

    section("reindex (rebuild index from vault = resilience)")
    stats = b.reindex()
    print("  reindex:", stats)
    assert stats["notes"] >= 3
    # Search still works after a full rebuild.
    hits3 = b.search("brain architecture", limit=2, searched_by="claude-code")
    assert hits3

    section("delete")
    ok = b.delete(n2["id"])
    assert ok and b.get(n2["id"]) is None
    print("  deleted avedit note OK")

    print("\nCORE PIPELINE: ALL ASSERTIONS PASSED ✅")

    # ---- API test -----------------------------------------------------
    section("REST API (auth + endpoints)")
    from fastapi.testclient import TestClient

    import api.server as srv

    srv.brain = b  # reuse the already-built brain (with fake embedder)
    client = TestClient(srv.app)

    # health: no auth
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    print("  /health ok, auth configured:", r.json()["auth"])

    # no key -> 401
    r = client.post("/search", json={"query": "x"})
    assert r.status_code == 401, r.status_code
    print("  no-key search -> 401 ✅")

    # bad key -> 401
    r = client.post("/search", json={"query": "x"}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    print("  bad-key search -> 401 ✅")

    # good key -> works, agent resolved from key
    h = {"Authorization": "Bearer test-key-aaa"}
    r = client.post("/save", json={"content": "n8n workflow connects brain via webhook", "title": "n8n hook", "category": "notes"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["agent"] == "claude-code"  # key aaa -> claude-code
    print("  authed /save ok, agent=", r.json()["agent"])

    r = client.post("/search", json={"query": "webhook", "limit": 3}, headers=h)
    assert r.status_code == 200 and r.json()["results"]
    print("  authed /search ok, results:", len(r.json()["results"]))

    r = client.get("/stats", headers=h)
    print("  /stats:", r.json())

    # audit log written
    from brain.config import config as cfg
    assert cfg.audit_log_path.exists(), "audit log missing"
    audit_lines = cfg.audit_log_path.read_text().strip().splitlines()
    assert any('"event": "save"' in l for l in audit_lines)
    assert all("test-key-aaa" not in l for l in audit_lines), "raw key leaked into audit log!"
    print("  audit log written, no raw keys leaked ✅")

    print("\nAPI: ALL ASSERTIONS PASSED ✅")
    print("\nSMOKE TEST COMPLETE — everything works.")


if __name__ == "__main__":
    main()
