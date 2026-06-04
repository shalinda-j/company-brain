"""The vault is the source of truth: Obsidian-compatible Markdown with YAML
frontmatter. v2 adds per-project isolation (vault/<project>/<category>/...) and
a `usefulness` score used for feedback-based re-ranking.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import config
from .security import new_id, safe_join, sanitize_id, slugify

VALID_CATEGORIES = {"conversations", "notes", "tasks", "knowledge", "activity"}


def sanitize_project(project: str | None) -> str:
    p = sanitize_id((project or config.default_project).strip() or config.default_project)
    return p or config.default_project


@dataclass
class Note:
    id: str
    title: str
    content: str
    project: str = "default"
    category: str = "notes"
    tags: list[str] = field(default_factory=list)
    source: str = ""
    agent: str = "default"
    created: str = ""
    updated: str = ""
    links: list[str] = field(default_factory=list)
    usefulness: int = 0

    def frontmatter(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "agent": self.agent,
            "created": self.created,
            "updated": self.updated,
            "links": self.links,
            "usefulness": self.usefulness,
        }

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def project_dir(project: str) -> Path:
    return safe_join(config.vault_dir, sanitize_project(project))


def _path_for(note: Note) -> Path:
    category = note.category if note.category in VALID_CATEGORIES else "notes"
    fname = f"{slugify(note.title)}--{sanitize_id(note.id)}.md"
    return safe_join(config.vault_dir, sanitize_project(note.project), category, fname)


def _render(note: Note) -> str:
    fm = yaml.safe_dump(note.frontmatter(), allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n\n# {note.title}\n\n{note.content}\n"


def ensure_project_dirs(project: str) -> None:
    base = project_dir(project)
    for sub in ("conversations", "notes", "tasks", "knowledge", "activity"):
        (base / sub).mkdir(parents=True, exist_ok=True)


def write_note(
    project: str,
    content: str,
    title: str | None = None,
    category: str = "notes",
    tags: list[str] | None = None,
    source: str = "",
    agent: str = "default",
    links: list[str] | None = None,
    note_id: str | None = None,
    usefulness: int = 0,
) -> Note:
    project = sanitize_project(project)
    ensure_project_dirs(project)
    nid = sanitize_id(note_id) if note_id else new_id()
    now = _now()
    if not title:
        first_line = content.strip().splitlines()[0] if content.strip() else "Untitled"
        title = first_line[:80]
    note = Note(
        id=nid,
        title=title,
        content=content,
        project=project,
        category=category if category in VALID_CATEGORIES else "notes",
        tags=tags or [],
        source=source,
        agent=agent,
        created=now,
        updated=now,
        links=links or [],
        usefulness=usefulness,
    )
    path = _path_for(note)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(note), encoding="utf-8")
    return note


def _parse(path: Path, project: str) -> Note | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fm: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            body = parts[2].lstrip("\n")
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        body = "\n".join(lines[1:]).lstrip("\n")
    try:
        usefulness = int(fm.get("usefulness") or 0)
    except (TypeError, ValueError):
        usefulness = 0
    return Note(
        id=str(fm.get("id") or path.stem),
        title=str(fm.get("title") or path.stem),
        content=body.rstrip(),
        project=str(fm.get("project") or project),
        category=str(fm.get("category") or path.parent.name),
        tags=list(fm.get("tags") or []),
        source=str(fm.get("source") or ""),
        agent=str(fm.get("agent") or "default"),
        created=str(fm.get("created") or ""),
        updated=str(fm.get("updated") or ""),
        links=list(fm.get("links") or []),
        usefulness=usefulness,
    )


def iter_notes(project: str):
    base = project_dir(project)
    if not base.exists():
        return
    for path in base.rglob("*.md"):
        note = _parse(path, project)
        if note:
            yield note, path


def list_projects() -> list[str]:
    if not config.vault_dir.exists():
        return []
    return sorted(p.name for p in config.vault_dir.iterdir() if p.is_dir())


def find_note(project: str, note_id: str) -> Note | None:
    nid = sanitize_id(note_id)
    for note, _ in iter_notes(project):
        if note.id == nid:
            return note
    return None


def find_path(project: str, note_id: str) -> Path | None:
    nid = sanitize_id(note_id)
    for note, path in iter_notes(project):
        if note.id == nid:
            return path
    return None


def recent_notes(project: str, n: int = 20) -> list[Note]:
    notes = [note for note, _ in iter_notes(project)]
    notes.sort(key=lambda x: x.updated or x.created or "", reverse=True)
    return notes[:n]


def update_note(note: Note) -> Note:
    """Persist changes to an existing note (preserving id/created, bumping updated)."""
    note.updated = _now()
    path = find_path(note.project, note.id)
    if path and path.exists():
        path.unlink()
    new_path = _path_for(note)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(_render(note), encoding="utf-8")
    return note


def delete_note(project: str, note_id: str) -> bool:
    path = find_path(project, note_id)
    if path and path.exists():
        path.unlink()
        return True
    return False
