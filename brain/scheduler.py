"""Optional heartbeat scheduler.

When HEARTBEAT_INTERVAL > 0, a background asyncio task periodically runs
brain.heartbeat_all() (usefulness decay + consolidation across all projects).
Disabled by default; maintenance can always be triggered manually via the API.
"""

from __future__ import annotations

import asyncio

from .config import config


async def heartbeat_loop(brain, stop: asyncio.Event) -> None:
    interval = config.heartbeat_interval
    if interval <= 0:
        return
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
        if stop.is_set():
            break
        try:
            await asyncio.to_thread(brain.heartbeat_all)
        except Exception:
            pass
