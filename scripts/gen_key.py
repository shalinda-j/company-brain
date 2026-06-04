#!/usr/bin/env python3
"""Generate a strong API key. Usage: python scripts/gen_key.py [agent-name]"""
import secrets
import sys

agent = sys.argv[1] if len(sys.argv) > 1 else "default"
key = secrets.token_urlsafe(32)
print(f"{key}:{agent}")
