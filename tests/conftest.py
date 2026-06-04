"""Shared pytest configuration and fixtures.

Environment is configured at import time (before any `brain` module is
imported). Every test gets an isolated brain backed by a fresh temp data dir and
the FakeEmbedder, so the suite runs offline with no model download. The shared
Qdrant client singleton is reset per test for isolation.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("BRAIN_API_KEYS", "test-key-aaa:claude-code,test-key-bbb:cursor")
os.environ.setdefault("LOG_SEARCHES", "true")
os.environ.pop("QDRANT_URL", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from tests._fake import FakeEmbedder  # noqa: E402


def _isolate(tmp_path, monkeypatch):
    from brain.config import config

    monkeypatch.setattr(config, "data_dir", tmp_path)
    import brain.core as core
    import brain.store as store

    # Reset the shared Qdrant client so it binds to this test's temp dir.
    monkeypatch.setattr(store, "_CLIENT", None)
    monkeypatch.setattr(core, "get_embedder", lambda *a, **k: FakeEmbedder())


@pytest.fixture()
def brain(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    import brain.core as core

    return core.Brain()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient

    import api.server as srv

    with TestClient(srv.app) as c:
        yield c
