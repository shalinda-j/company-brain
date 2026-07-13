"""Entity resolution / canonicalization.

Maps surface entity names to a canonical form via (1) normalization and (2) an
explicit alias map (alias -> canonical), stored as a JSON file shared across
projects. This lets "qdrant db" and "Qdrant" collapse into one graph node.
"""

from __future__ import annotations

import json
import re
import threading

from .config import config

_LOCK = threading.Lock()

# aliases.json cache: path -> (mtime, data); re-read only when mtime changes.
_ALIAS_CACHE: dict[str, tuple[float, dict[str, str]]] = {}


def _path():
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config.data_dir / "aliases.json"


def _load() -> dict[str, str]:
    p = _path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    cached = _ALIAS_CACHE.get(str(p))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    _ALIAS_CACHE[str(p)] = (mtime, data)
    return data


def normalize(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", (name or "").lower()).strip()
    return re.sub(r"\s+", " ", n)


def set_alias(alias: str, canonical: str) -> dict[str, str]:
    with _LOCK:
        data = dict(_load())  # copy: don't mutate the cached dict in place
        data[normalize(alias)] = canonical.strip()
        _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return data


def aliases() -> dict[str, str]:
    return _load()


def canonical(name: str) -> str:
    data = _load()
    key = normalize(name)
    if key in data:
        return data[key]
    return (name or "").strip()
