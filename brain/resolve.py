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


def _path():
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config.data_dir / "aliases.json"


def _load() -> dict[str, str]:
    p = _path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def normalize(name: str) -> str:
    n = re.sub(r"[^\w\s-]", "", (name or "").lower()).strip()
    return re.sub(r"\s+", " ", n)


def set_alias(alias: str, canonical: str) -> dict[str, str]:
    with _LOCK:
        data = _load()
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
