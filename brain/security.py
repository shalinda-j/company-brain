"""Security primitives: API-key auth, constant-time comparison, audit logging,
and path/id sanitization to prevent traversal.

Design notes (privacy & security):
- API keys live only in the environment. They are mapped to an "agent" identity
  so the brain knows *who* wrote/searched what (multi-agent visibility).
- We compare keys in constant time to avoid timing attacks.
- Raw keys are NEVER written to logs. The audit log records the agent name only.
- All note ids / paths are sanitized so a request can never escape the vault dir.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from pathlib import Path

from .config import config

_AUDIT_LOCK = threading.Lock()
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_\-]")


def parse_api_keys(raw: str) -> dict[str, str]:
    """Parse "key:agent,key2:agent2" into {key: agent}. Bare keys -> 'default'."""
    keys: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            key, agent = part.split(":", 1)
            key, agent = key.strip(), agent.strip() or "default"
        else:
            key, agent = part, "default"
        if key:
            keys[key] = agent
    return keys


_API_KEYS = parse_api_keys(config.api_keys_raw)


def verify_key(presented: str | None) -> str | None:
    """Return the agent name for a valid key, or None. Constant-time."""
    if not presented or not _API_KEYS:
        return None
    matched_agent: str | None = None
    # Iterate over all keys (constant work) using hmac.compare_digest.
    for key, agent in _API_KEYS.items():
        if hmac.compare_digest(presented, key):
            matched_agent = agent
    return matched_agent


def auth_configured() -> bool:
    return bool(_API_KEYS)


def sanitize_id(raw: str) -> str:
    """Sanitize an arbitrary id so it is safe to use in a filename / path."""
    cleaned = _SAFE_ID_RE.sub("-", raw.strip())
    cleaned = cleaned.strip("-.") or "note"
    return cleaned[:120]


def slugify(text: str, max_len: int = 60) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return (text[:max_len] or "untitled").strip("-")


def safe_join(base: Path, *parts: str) -> Path:
    """Join paths and guarantee the result stays inside `base`."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Path traversal attempt blocked")
    return target


def new_id() -> str:
    """Time-sortable unique id, e.g. 20260604-100000-a1b2c3."""
    import secrets

    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{ts}-{secrets.token_hex(3)}"


def audit(event: str, agent: str | None = None, **fields) -> None:
    """Append a structured audit record. Never logs secrets."""
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "agent": agent or "anonymous",
        **fields,
    }
    line = json.dumps(record, ensure_ascii=False)
    with _AUDIT_LOCK:
        config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with config.audit_log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def key_fingerprint(key: str) -> str:
    """A short, non-reversible fingerprint of a key (for safe display only)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]
