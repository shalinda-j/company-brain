"""The vault is the source of truth: plain Obsidian-compatible Markdown files
with YAML frontmatter. You can open the whole thing in Obsidian, browse it,
and version it with git. The vector index is rebuildable from these files.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .config import config
from .security import new_id, safe_join, sanitize_id, slugify

VALID_CATEGORIES = {"conversations", "notes", "tasks", "knowledge", "activity"}


@dataclass
class Note:
    id: str
    title: str
    content: str
    category: str = "notes"
    tags: list[str] = field(default_factory=list)
    source: str = ""
    agent: str = "default"
    created: str = ""
    updated: str = ""
    links: list[str] = field(default_factory=list)

    def frontmatter(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "agent": self.agent,
            "created": self.created,
            "updated": self.updated,
            "links": self.links,
        }

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path_for(note: Note) -> Path:
    category = note.category if note.category in VALID_CATEGORIES else "notes"
    fname = f"{slugify(note.title)}--{sanitize_id(note.id)}.md"
    return safe_join(config.vault_dir, category, fname)


def _render(note: Note) -> str:
    fm = yaml.safe_dump(note.frontmatter(), allow_unicode=True, sort_keys=False).strip()
    return f"---\n{fm}\n---\n\n# {note.title}\n\n{note.content}\n"


def write_note(
    content: str,
    title: str | None = None,
    category: str = "notes",
    tags: list[str] | None = None,
    source: str = "",
    agent: str = "default",
    links: list[str] | None = None,
    note_id: str | None = None,
) -> Note:
    nid = sanitize_id(note_id) if note_id else new_id()
    now = _now()
    if not title:
        first_line = content.strip().splitlines()[0] if content.strip() else "Untitled"
        title = first_line[:80]
    note = Note(
        id=nid,
        title=title,
        content=content,
        category=category if category in VALID_CATEGORIES else "notes",
        tags=tags or [],
        source=source,
        agent=agent,
        created=now,
        updated=now,
        links=links or [],
    )
    path = _path_for(note)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(note), encoding="utf-8")
    return note


def _parse(path: Path) -> Note | None:
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
    # Strip a leading "# Title" heading from the body for clean content.
    lines = body.splitlines()
    if lines and lines[0].startswith("# "):
        body = "\n".join(lines[1:]).lstrip("\n")
    return Note(
        id=str(fm.get("id") or path.stem),
        title=str(fm.get("title") or path.stem),
        content=body.rstrip(),
        category=str(fm.get("category") or path.parent.name),
        tags=list(fm.get("tags") or []),
        source=str(fm.get("source") or ""),
        agent=str(fm.get("agent") or "default"),
        created=str(fm.get("created") or ""),
        updated=str(fm.get("updated") or ""),
        links=list(fm.get("links") or []),
    )


def iter_notes():
    for path in config.vault_dir.rglob("*.md"):
        note = _parse(path)
        if note:
            yield note, path


def find_note(note_id: str) -> Note | None:
    nid = sanitize_id(note_id)
    for note, _ in iter_notes():
        if note.id == nid:
            return note
    return None


def find_path(note_id: str) -> Path | None:
    nid = sanitize_id(note_id)
    for note, path in iter_notes():
        if note.id == nid:
            return path
    return None


def recent_notes(n: int = 20) -> list[Note]:
    notes = [note for note, _ in iter_notes()]
    notes.sort(key=lambda x: (x.updated or x.created or ""), reverse=True)
    return notes[:n]


def delete_note(note_id: str) -> bool:
    path = find_path(note_id)
    if path and path.exists():
        path.unlink()
        return True
    return False
