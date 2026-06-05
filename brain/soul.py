"""SOUL — the agent's sense-of-self context for a project.

Stored as Markdown alongside the project's notes. There is a shared project SOUL
(_SOUL.md) plus optional per-agent overlays (_souls/<agent>.md). Recall merges the
shared SOUL with the requesting agent's overlay, so one agent's learned principle
no longer rewrites every other agent's identity.
"""

from __future__ import annotations

import re
import time

from . import vault

_DEFAULT = """# SOUL

## Identity
(Describe who this agent/assistant is and its role.)

## Values & principles
- Be accurate and honest.

## Learned principles
"""


def _safe_agent(agent: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", (agent or "agent").strip().lower()).strip("-") or "agent"


def _path(project: str, agent: str | None = None):
    base = vault.project_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    if agent:
        d = base / "_souls"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{_safe_agent(agent)}.md"
    return base / "_SOUL.md"


def get_soul(project: str, agent: str | None = None) -> str:
    p = _path(vault.sanitize_project(project), agent)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "" if agent else _DEFAULT


def set_soul(project: str, text: str, agent: str | None = None) -> str:
    p = _path(vault.sanitize_project(project), agent)
    fallback = "" if agent else _DEFAULT
    p.write_text(text if text.strip() else fallback, encoding="utf-8")
    return get_soul(project, agent)


def append_principle(project: str, principle: str, agent: str | None = None) -> str:
    project = vault.sanitize_project(project)
    text = get_soul(project, agent) or (_DEFAULT if not agent else "## Learned principles\n")
    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    line = f"- {principle.strip()}  _(learned {stamp})_"
    if "## Learned principles" in text:
        text = text.rstrip() + "\n" + line + "\n"
    else:
        text = text.rstrip() + "\n\n## Learned principles\n" + line + "\n"
    return set_soul(project, text, agent)


def merged_soul(project: str, agent: str | None = None) -> str:
    """Shared project SOUL + the agent's overlay (if any)."""
    shared = get_soul(project).strip()
    if not agent:
        return shared
    overlay = get_soul(project, agent).strip()
    if overlay:
        return f"{shared}\n\n## Agent overlay ({agent})\n{overlay}".strip()
    return shared
