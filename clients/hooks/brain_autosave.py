#!/usr/bin/env python
"""Claude Code `Stop` hook: auto-capture each finished exchange into Company Brain.

Reads the hook JSON on stdin, pulls the latest human prompt + assistant reply from
the transcript, and POSTs it to the brain's /ingest endpoint, scoped per project
(BRAIN_PROJECT env var if set, else cwd basename). Fail-safe: any error is swallowed
and it always exits 0, so it can never block or break a Claude Code turn.

Setup
-----
1. Put this file somewhere stable, e.g. ~/.claude/hooks/brain_autosave.py
2. Export the brain config in your environment (or set it in the hook command):
       BRAIN_URL=https://YOUR_BRAIN_HOST
       BRAIN_API_KEY=<YOUR_API_KEY>
       BRAIN_VERIFY_TLS=true        # false only for a self-signed / IP cert
       BRAIN_PROJECT=<project>      # optional; defaults to the cwd basename
3. Register it in ~/.claude/settings.json:
       {
         "hooks": {
           "Stop": [
             { "hooks": [ { "type": "command",
                            "command": "python \"<path to this file>\"",
                            "timeout": 15, "async": true } ] }
           ]
         }
       }
If BRAIN_URL / BRAIN_API_KEY are not set, the hook does nothing (exits 0).
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

BRAIN_URL = os.environ.get("BRAIN_URL", "").rstrip("/")
BRAIN_API_KEY = os.environ.get("BRAIN_API_KEY", "")
AGENT = os.environ.get("BRAIN_AGENT", "claude-code")
PROJECT = os.environ.get("BRAIN_PROJECT", "")
VERIFY_TLS = os.environ.get("BRAIN_VERIFY_TLS", "true").lower() not in {"0", "false", "no"}
MAX_SIDE = 6000  # cap each side so bodies stay small


def _text_from_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            b["text"] for b in content
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
        ).strip()
    return ""


def _is_tool_result(content) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def main() -> int:
    if not BRAIN_URL or not BRAIN_API_KEY:
        return 0  # not configured

    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    tpath = data.get("transcript_path")
    cwd = data.get("cwd") or os.getcwd()
    project = PROJECT or Path(cwd).name or "default"
    if not tpath or not os.path.exists(tpath):
        return 0

    last_user = ""
    last_assistant = ""
    with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            etype = e.get("type")
            content = (e.get("message") or {}).get("content")
            if etype == "user":
                if e.get("isMeta") or _is_tool_result(content):
                    continue
                t = _text_from_content(content)
                if t:
                    last_user = t
            elif etype == "assistant":
                t = _text_from_content(content)
                if t:
                    last_assistant = t

    if not last_assistant and not last_user:
        return 0

    text = ""
    if last_user:
        text += "User: " + last_user[:MAX_SIDE] + "\n\n"
    if last_assistant:
        text += "Assistant: " + last_assistant[:MAX_SIDE]

    payload = json.dumps({
        "text": text,
        "title": (last_user[:70] or "chat").replace("\n", " "),
        "source": "claude-code-hook",
        "project": project,
    }).encode("utf-8")

    ctx = ssl.create_default_context()
    if not VERIFY_TLS:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        BRAIN_URL + "/ingest", data=payload, method="POST",
        headers={
            "Authorization": "Bearer " + BRAIN_API_KEY,
            "Content-Type": "application/json",
            "X-Agent": AGENT,
        },
    )
    try:
        urllib.request.urlopen(req, timeout=8, context=ctx).read()
    except Exception:
        pass  # never block the turn on a brain hiccup
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
