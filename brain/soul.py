"""SOUL — the agent's sense-of-self context for a project.

Stored as a plain Markdown file (_SOUL.md) alongside the project's notes, so it
is human-editable and git-friendly. It is always included in multi-layer recall.
Agents can append "learned principles" to it over time.
"""

from __future__ import annotations

import time

from . import vault

_DEFAULT = """# SOUL

## Identity
(Describe who this agent/assistant is and its role.)

## Values & principles
- Be accurate and honest.

## Learned principles
"""


def _path(project: str):
    base = vault.project_dir(project)
    base.mkdir(parents=True, exist_ok=True)
    return base / "_SOUL.md"


def get_soul(project: str) -> str:
    p = _path(vault.sanitize_project(project))
    if p.exists():
        return p.read_text(encoding="utf-8")
    return _DEFAULT


def set_soul(project: str, text: str) -> str:
    p = _path(vault.sanitize_project(project))
    p.write_text(text if text.strip() else _DEFAULT, encoding="utf-8")
    return get_soul(project)


def append_principle(project: str, principle: str) -> str:
    project = vault.sanitize_project(project)
    text = get_soul(project)
    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    line = f"- {principle.strip()}  _(learned {stamp})_"
    if "## Learned principles" in text:
        text = text.rstrip() + "\n" + line + "\n"
    else:
        text = text.rstrip() + "\n\n## Learned principles\n" + line + "\n"
    return set_soul(project, text)
