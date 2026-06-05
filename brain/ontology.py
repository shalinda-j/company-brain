"""Lightweight ontology — a tag taxonomy (tag -> parent tag).

Stored as one JSON file shared across projects. Used to expand a tag filter to
include its descendant tags during search.
"""

from __future__ import annotations

import json
import threading

from .config import config

_LOCK = threading.Lock()


def _path():
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config.data_dir / "ontology.json"


def _load() -> dict[str, str]:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def set_parent(tag: str, parent: str) -> dict[str, str]:
    with _LOCK:
        data = _load()
        data[tag.strip().lower()] = parent.strip().lower()
        _path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data


def taxonomy() -> dict[str, str]:
    return _load()


def descendants(tag: str) -> list[str]:
    """All tags whose ancestor chain includes `tag` (plus the tag itself)."""
    data = _load()
    tag = tag.strip().lower()
    out = {tag}
    changed = True
    while changed:
        changed = False
        for child, parent in data.items():
            if parent in out and child not in out:
                out.add(child)
                changed = True
    return sorted(out)
