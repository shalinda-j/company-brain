"""Detect and optionally redact secrets / PII before a memory is stored.

Heuristic, regex-based — deliberately conservative to limit false positives.
Findings never include the secret itself, only its type and a masked preview.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}")),
    (
        "assignment_secret",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"]?([A-Za-z0-9._/+-]{12,})"
        ),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("high_entropy_token", re.compile(r"\b[A-Za-z0-9_-]{40,}\b")),
]


def _mask(s: str) -> str:
    if len(s) <= 8:
        return "***"
    return f"{s[:3]}…{s[-2:]}"


def scan(text: str) -> list[dict]:
    findings: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for kind, pat in _PATTERNS:
        for m in pat.finditer(text or ""):
            key = (kind, m.start())
            if key in seen:
                continue
            seen.add(key)
            findings.append({"type": kind, "preview": _mask(m.group(0))})
    return findings


def redact(text: str) -> tuple[str, list[dict]]:
    findings = scan(text)
    out = text or ""
    for kind, pat in _PATTERNS:
        out = pat.sub(lambda m, k=kind: f"[REDACTED:{k}]", out)
    return out, findings
