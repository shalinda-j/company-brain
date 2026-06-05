"""Preferential context — simple key/value preferences for a project.

Stored as a plain Markdown file (_PREFERENCES.md) of "key: value" lines, so it
is human-editable and git-friendly. Always included in multi-layer recall.
"""

from __future__ import annotations

from . import vault


def _path(project: str):
    base = vault.project_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    return base / "_PREFERENCES.md"


def all_prefs(project: str) -> dict[str, str]:
    p = _path(vault.sanitize_project(project))
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


def _write(project: str, prefs: dict[str, str]) -> None:
    p = _path(vault.sanitize_project(project))
    lines = ["# Preferences", ""]
    lines += [f"{k}: {v}" for k, v in sorted(prefs.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_pref(project: str, key: str, value: str) -> dict[str, str]:
    prefs = all_prefs(project)
    prefs[key.strip()] = value.strip()
    _write(project, prefs)
    return prefs


def delete_pref(project: str, key: str) -> dict[str, str]:
    prefs = all_prefs(project)
    prefs.pop(key.strip(), None)
    _write(project, prefs)
    return prefs
