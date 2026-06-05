"""The vault is the source of truth: Obsidian-compatible Markdown with YAML
frontmatter. v0.0.1.3 adds archived/user/importance on notes; any file or
directory whose name starts with "_" (e.g. _SOUL.md, _blocks/, _FACTS.json) is
reserved and never treated as an ordinary memory.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import config
from .security import new_id, safe_join, sanitize_id, slugify

VALID_CATEGORIES = {
    "conversations",
    "notes",
    "tasks",
    "knowledge",
    "activity",
    "procedure",
    "self",
}


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
    entities: list[str] = field(default_factory=list)
    usefulness: int = 0
    access_count: int = 0
    importance: int = 1
    archived: bool = False
    user: str = ""

    def frontmatter(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "project": self.project,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "agent": self.agent,
            "user": self.user,
            "created": self.created,
            "updated": self.updated,
            "links": self.links,
            "entities": self.entities,
            "usefulness": self.usefulness,
            "access_count": self.access_count,
            "importance": self.importance,
            "archived": self.archived,
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
    for sub in VALID_CATEGORIES:
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
    entities: list[str] | None = None,
    note_id: str | None = None,
    usefulness: int = 0,
    access_count: int = 0,
    importance: int = 1,
    archived: bool = False,
    user: str = "",
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
        entities=entities or [],
        usefulness=usefulness,
        access_count=access_count,
        importance=importance,
        archived=archived,
        user=user,
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

    def _int(v, default=0):
        try:
            return int(v if v is not None else default)
        except (TypeError, ValueError):
            return default

    return Note(
        id=str(fm.get("id") or path.stem),
        title=str(fm.get("title") or path.stem),
        content=body.rstrip(),
        project=str(fm.get("project") or project),
        category=str(fm.get("category") or path.parent.name),
        tags=list(fm.get("tags") or []),
        source=str(fm.get("source") or ""),
        agent=str(fm.get("agent") or "default"),
        user=str(fm.get("user") or ""),
        created=str(fm.get("created") or ""),
        updated=str(fm.get("updated") or ""),
        links=list(fm.get("links") or []),
        entities=list(fm.get("entities") or []),
        usefulness=_int(fm.get("usefulness")),
        access_count=_int(fm.get("access_count")),
        importance=_int(fm.get("importance"), 1),
        archived=bool(fm.get("archived") or False),
    )


def _is_reserved(path: Path, base: Path) -> bool:
    """True if any path segment below the project root starts with '_'."""
    try:
        rel = path.relative_to(base)
    except ValueError:
        return True
    return any(part.startswith("_") for part in rel.parts)


def iter_notes(project: str):
    base = project_dir(project)
    if not base.exists():
        return
    for path in base.rglob("*.md"):
        if _is_reserved(path, base):
            continue
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


def recent_notes(project: str, n: int = 20, include_archived: bool = True) -> list[Note]:
    notes = [note for note, _ in iter_notes(project)]
    if not include_archived:
        notes = [n for n in notes if not n.archived]
    notes.sort(key=lambda x: x.updated or x.created or "", reverse=True)
    return notes[:n]


def update_note(note: Note) -> Note:
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
