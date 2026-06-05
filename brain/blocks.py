"""Core memory blocks (MemGPT/Letta-style).

Named, size-limited, human-editable context units stored under _blocks/<name>.md.
They are always injected into recall. The persona/identity block is the SOUL
(managed by brain.soul); blocks.py manages any additional named blocks such as
"human" (facts about the user).
"""

from __future__ import annotations

import re

from . import vault
from .config import config


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (name or "block").strip().lower()).strip("-") or "block"


def _dir(project: str):
    d = vault.project_dir(vault.sanitize_project(project)) / "_blocks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(project: str, name: str):
    return _dir(project) / f"{_safe(name)}.md"


def _cap(text: str) -> str:
    limit = config.block_char_limit
    if len(text) > limit:
        return text[:limit].rstrip() + "\n…(truncated)"
    return text


def get_block(project: str, name: str) -> str:
    p = _path(project, name)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def set_block(project: str, name: str, text: str) -> str:
    _path(project, name).write_text(_cap(text), encoding="utf-8")
    return get_block(project, name)


def append_block(project: str, name: str, text: str) -> str:
    cur = get_block(project, name)
    joined = (cur.rstrip() + "\n" + text.strip()).strip() if cur else text.strip()
    return set_block(project, name, joined)


def list_blocks(project: str) -> dict[str, str]:
    out: dict[str, str] = {}
    d = _dir(project)
    for p in sorted(d.glob("*.md")):
        out[p.stem] = p.read_text(encoding="utf-8")
    return out
