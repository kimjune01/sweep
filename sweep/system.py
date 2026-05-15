"""System health: CPU, memory, and Temporal running-workflow count.

Cached at ~/.sweep/cache/system.json with a 4s TTL — repeat refreshes inside
one cockpit tick reuse the result.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path


CACHE = Path.home() / ".sweep" / "cache" / "system.json"
CACHE_TTL = 4.0
TEMPORAL_ADDR = "localhost:7233"


def system_status() -> dict:
    """Snapshot of CPU / memory / running workflows.

    Returns {cpu, mem, running, fetched_at}. `running` is a list of dicts
    with id/type/started — empty when Temporal is unreachable.
    """
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text())
            if time.time() - data.get("fetched_at", 0) < CACHE_TTL:
                return data
        except (json.JSONDecodeError, OSError):
            pass

    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
    except Exception:
        cpu = 0.0
        mem = 0.0

    running: list[dict] = []
    try:
        running = asyncio.run(_running_workflows())
    except Exception:
        running = []

    result = {
        "cpu": cpu,
        "mem": mem,
        "running": running,
        "fetched_at": time.time(),
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CACHE.write_text(json.dumps(result))
    except OSError:
        pass
    return result


async def _running_workflows(limit: int = 10) -> list[dict]:
    """Best-effort Temporal query for running workflows. Short timeouts so
    a missing server doesn't stall the cockpit."""
    from temporalio.client import Client

    client = await asyncio.wait_for(Client.connect(TEMPORAL_ADDR), timeout=0.5)

    async def _collect() -> list[dict]:
        iterator = client.list_workflows("ExecutionStatus='Running'")
        out: list[dict] = []
        async for wf in iterator:
            out.append({
                "id": wf.id,
                "type": wf.workflow_type,
                "started": wf.start_time.isoformat() if wf.start_time else None,
            })
            if len(out) >= limit:
                break
        return out

    return await asyncio.wait_for(_collect(), timeout=1.0)
