"""Real-time session / checkpoint layer.

A crash-recovery journal: lightweight, append-only checkpoints of "what am I
doing right now" — separate from the semantic memory vault so high-frequency
writes never pollute recall. Each checkpoint is one JSON line under
_sessions/<session>.jsonl (a reserved dir, never indexed/embedded). Pair the
optional git_ref with the git auto-snapshot daemon to also recover file state.
"""

from __future__ import annotations

import json
import threading
import time

from . import redact, vault
from .config import config
from .security import new_id, sanitize_id

_LOCK = threading.RLock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe(name: str) -> str:
    return sanitize_id((name or "default").strip() or "default")


def _dir(project: str):
    d = vault.project_dir(vault.sanitize_project(project)) / "_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(project: str, session: str):
    return _dir(project) / f"{_safe(session)}.jsonl"


def add_checkpoint(
    project: str,
    note: str,
    session: str = "default",
    agent: str = "default",
    files: list[str] | None = None,
    git_ref: str = "",
    next_step: str = "",
    status: str = "working",
) -> dict:
    project = vault.sanitize_project(project)
    findings = redact.scan(note)
    if config.redact_on_save and findings:
        note, findings = redact.redact(note)
    rec = {
        "id": new_id(),
        "ts": _now(),
        "session": _safe(session),
        "agent": agent,
        "note": note,
        "files": files or [],
        "git_ref": git_ref,
        "next": next_step,
        "status": status,
    }
    with _LOCK:
        with _path(project, session).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rec["pii_findings"] = findings
    return rec


def _read(project: str, session: str) -> list[dict]:
    p = _path(project, session)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_checkpoints(project: str, session: str) -> list[dict]:
    """All checkpoints for a session (empty list if none / already closed)."""
    return _read(vault.sanitize_project(project), session)


def close(project: str, session: str) -> int:
    """Mark a session closed by renaming its journal to <session>.jsonl.closed.
    Returns the number of checkpoints it held (0 if nothing to close)."""
    project = vault.sanitize_project(project)
    n = len(_read(project, session))
    with _LOCK:
        p = _path(project, session)
        if p.exists():
            target = p.with_name(p.name + ".closed")
            if target.exists():
                target.unlink()
            p.rename(target)
    return n


def export_sessions(project: str) -> dict[str, str]:
    """filename -> raw JSONL content (open and closed), for export bundles."""
    d = _dir(vault.sanitize_project(project))
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.jsonl*"))}


def import_sessions(project: str, data: dict[str, str]) -> int:
    """Restore session journals from an export bundle. Returns files written."""
    d = _dir(vault.sanitize_project(project))
    n = 0
    for name, text in (data or {}).items():
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        if not name.endswith((".jsonl", ".jsonl.closed")):
            continue
        (d / name).write_text(text, encoding="utf-8")
        n += 1
    return n


def list_sessions(project: str) -> list[dict]:
    project = vault.sanitize_project(project)
    d = _dir(project)
    out = []
    for p in d.glob("*.jsonl"):
        recs = _read(project, p.stem)
        if not recs:
            continue
        last = recs[-1]
        out.append(
            {
                "session": p.stem,
                "checkpoints": len(recs),
                "last_ts": last.get("ts"),
                "last_note": last.get("note", "")[:120],
            }
        )
    out.sort(key=lambda x: x.get("last_ts") or "", reverse=True)
    return out


def _latest_session(project: str) -> str | None:
    sessions = list_sessions(project)
    return sessions[0]["session"] if sessions else None


def resume(project: str, session: str | None = None, n: int = 5) -> dict:
    project = vault.sanitize_project(project)
    sess = _safe(session) if session else _latest_session(project)
    if not sess:
        return {"project": project, "session": None, "latest": None, "recent": [], "found": False}
    recs = _read(project, sess)
    recent = recs[-n:][::-1]
    latest = recent[0] if recent else None
    return {
        "project": project,
        "session": sess,
        "latest": latest,
        "recent": recent,
        "found": bool(latest),
    }
