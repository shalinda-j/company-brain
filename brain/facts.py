"""Bi-temporal facts layer (Zep/Graphiti-style).

A fact has a subject (+ optional predicate) and a value. Each fact records when
it was ingested and the period it is valid for. Storing a new fact for the same
(subject, predicate) invalidates the previous current fact — but keeps it as
history (it is never deleted), so the agent reasons with the latest state while
retaining a full audit trail. Stored as a git-friendly JSON file per project.
"""

from __future__ import annotations

import json
import threading
import time

from . import vault
from .security import new_id

_LOCK = threading.RLock()


def _path(project: str):
    base = vault.project_dir(vault.sanitize_project(project))
    base.mkdir(parents=True, exist_ok=True)
    return base / "_FACTS.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load(project: str) -> list[dict]:
    p = _path(project)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(project: str, facts: list[dict]) -> None:
    _path(project).write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def add_fact(
    project: str,
    subject: str,
    value: str,
    predicate: str = "is",
    source: str = "",
    agent: str = "default",
    valid_from: str | None = None,
) -> dict:
    project = vault.sanitize_project(project)
    now = _now()
    with _LOCK:
        facts = _load(project)
        invalidated = []
        for f in facts:
            if (
                f.get("invalidated_at") is None
                and _norm(f.get("subject")) == _norm(subject)
                and _norm(f.get("predicate")) == _norm(predicate)
            ):
                f["invalidated_at"] = now
                f["valid_to"] = now
                invalidated.append(f["id"])
        fact = {
            "id": new_id(),
            "subject": subject.strip(),
            "predicate": predicate.strip() or "is",
            "value": value.strip(),
            "valid_from": valid_from or now,
            "valid_to": None,
            "ingested_at": now,
            "invalidated_at": None,
            "source": source,
            "agent": agent,
        }
        facts.append(fact)
        _save(project, facts)
    fact["invalidated"] = invalidated
    return fact


def current_facts(project: str, subject: str | None = None) -> list[dict]:
    facts = _load(vault.sanitize_project(project))
    out = [f for f in facts if f.get("invalidated_at") is None]
    if subject:
        out = [f for f in out if _norm(f.get("subject")) == _norm(subject)]
    return out


def history(project: str, subject: str) -> list[dict]:
    facts = _load(vault.sanitize_project(project))
    out = [f for f in facts if _norm(f.get("subject")) == _norm(subject)]
    out.sort(key=lambda f: f.get("ingested_at") or "")
    return out


def all_facts(project: str) -> list[dict]:
    return _load(vault.sanitize_project(project))


def contradictions(project: str) -> list[dict]:
    """Current facts that share a (subject, predicate) — should be at most one each."""
    facts = current_facts(project)
    by_key: dict[tuple, list[dict]] = {}
    for f in facts:
        by_key.setdefault((_norm(f["subject"]), _norm(f["predicate"])), []).append(f)
    return [
        {"subject": k[0], "predicate": k[1], "values": [x["value"] for x in v]}
        for k, v in by_key.items()
        if len(v) > 1
    ]
