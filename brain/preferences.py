"""Preferential context — key/value preferences for a project.

Shared project preferences live in _PREFERENCES.md. Optional per-agent overlays
live in _prefs/<agent>.md. Recall merges shared + agent (agent overrides shared),
so agents can hold their own preferences without clobbering each other.
"""

from __future__ import annotations

import re

from . import vault


def _safe_agent(agent: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (agent or "agent").strip().lower()).strip("-") or "agent"


def _path(project: str, agent: str | None = None):
    base = vault.project_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    if agent:
        d = base / "_prefs"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{_safe_agent(agent)}.md"
    return base / "_PREFERENCES.md"


def all_prefs(project: str, agent: str | None = None) -> dict[str, str]:
    p = _path(vault.sanitize_project(project), agent)
    prefs: dict[str, str] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            if k.strip():
                prefs[k.strip()] = v.strip()
    return prefs


def merged_prefs(project: str, agent: str | None = None) -> dict[str, str]:
    prefs = all_prefs(project)
    if agent:
        prefs.update(all_prefs(project, agent))
    return prefs


def _write(project: str, prefs: dict[str, str], agent: str | None = None) -> None:
    p = _path(vault.sanitize_project(project), agent)
    lines = ["# Preferences", ""]
    lines += [f"{k}: {v}" for k, v in sorted(prefs.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_pref(project: str, key: str, value: str, agent: str | None = None) -> dict[str, str]:
    prefs = all_prefs(project, agent)
    prefs[key.strip()] = value.strip()
    _write(project, prefs, agent)
    return prefs


def delete_pref(project: str, key: str, agent: str | None = None) -> dict[str, str]:
    prefs = all_prefs(project, agent)
    prefs.pop(key.strip(), None)
    _write(project, prefs, agent)
    return prefs
