"""Core memory blocks (MemGPT/Letta-style).

Named, size-limited, human-editable context units. Shared project blocks live in
_blocks/<name>.md; optional per-agent blocks live in _blocks/<agent>/<name>.md.
Recall merges shared + agent blocks (agent overrides a same-named shared block).
"""

from __future__ import annotations

import re

from . import vault
from .config import config


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (name or "block").strip().lower()).strip("-") or "block"


def _dir(project: str, agent: str | None = None):
    d = vault.project_dir(vault.sanitize_project(project)) / "_blocks"
    if agent:
        d = d / _safe(agent)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(project: str, name: str, agent: str | None = None):
    return _dir(project, agent) / f"{_safe(name)}.md"


def _cap(text: str) -> str:
    limit = config.block_char_limit
    if len(text) > limit:
        return text[:limit].rstrip() + "\n…(truncated)"
    return text


def get_block(project: str, name: str, agent: str | None = None) -> str:
    p = _path(project, name, agent)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def set_block(project: str, name: str, text: str, agent: str | None = None) -> str:
    _path(project, name, agent).write_text(_cap(text), encoding="utf-8")
    return get_block(project, name, agent)


def append_block(project: str, name: str, text: str, agent: str | None = None) -> str:
    cur = get_block(project, name, agent)
    joined = (cur.rstrip() + "\n" + text.strip()).strip() if cur else text.strip()
    return set_block(project, name, joined, agent)


def list_blocks(project: str, agent: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(_dir(project).glob("*.md")):
        out[p.stem] = p.read_text(encoding="utf-8")
    if agent:
        for p in sorted(_dir(project, agent).glob("*.md")):
            out[p.stem] = p.read_text(encoding="utf-8")
    return out
