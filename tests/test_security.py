"""Unit tests for security primitives and chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain.chunking import chunk_text
from brain.security import (
    parse_api_keys,
    safe_join,
    sanitize_id,
    slugify,
)


def test_parse_api_keys_pairs_and_bare():
    keys = parse_api_keys("k1:agentA, k2:agentB, k3")
    assert keys["k1"] == "agentA"
    assert keys["k2"] == "agentB"
    assert keys["k3"] == "default"


def test_verify_key(monkeypatch):
    import brain.security as sec

    monkeypatch.setattr(sec, "_API_KEYS", {"good": "claude-code"})
    assert sec.verify_key("good") == "claude-code"
    assert sec.verify_key("bad") is None
    assert sec.verify_key(None) is None


def test_sanitize_id_strips_traversal():
    assert "/" not in sanitize_id("../../etc/passwd")
    assert "\\" not in sanitize_id("..\\..\\windows")
    assert sanitize_id("") == "note"


def test_slugify_unicode():
    assert slugify("Hello World!") == "hello-world"
    # Non-ascii reduces to a safe fallback rather than crashing.
    assert isinstance(slugify("සිංහල title"), str)


def test_safe_join_blocks_escape(tmp_path: Path):
    safe_join(tmp_path, "notes", "ok.md")  # fine
    with pytest.raises(ValueError):
        safe_join(tmp_path, "..", "..", "etc", "passwd")


def test_chunk_text_basic():
    assert chunk_text("") == []
    text = "para one\n\npara two\n\npara three"
    chunks = chunk_text(text, size=1000, overlap=100)
    assert len(chunks) == 1


def test_chunk_text_splits_long_paragraph():
    long = "x" * 5000
    chunks = chunk_text(long, size=1000, overlap=150)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)
