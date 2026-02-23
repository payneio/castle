"""Log streaming — tail journalctl output for systemd-managed services."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, status
from starlette.responses import StreamingResponse

from castle_api.config import get_castle_root

router = APIRouter(prefix="/logs", tags=["logs"])

UNIT_PREFIX = "castle-"


@router.get("/{name}", response_model=None)
async def get_logs(
    name: str,
    n: int = Query(default=100, ge=1, le=5000, description="Number of lines"),
    follow: bool = Query(default=False, description="Stream new lines via SSE"),
) -> StreamingResponse | dict:
    """Get logs for a systemd-managed service."""
    root = get_castle_root()
    if root:
        from castle_core.config import load_config

        config = load_config(root)
        is_managed = (
            (name in config.services and config.services[name].manage is not None)
            or (name in config.jobs and config.jobs[name].manage is not None)
        )
        if not is_managed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"'{name}' is not a managed service",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Castle root not available",
        )

    unit = f"{UNIT_PREFIX}{name}.service"

    if follow:
        return StreamingResponse(
            _follow_logs(unit, n),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Static tail
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "--user",
        "-u",
        unit,
        "-n",
        str(n),
        "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    lines = (stdout or b"").decode().splitlines()
    return {"component": name, "lines": lines}


async def _follow_logs(unit: str, n: int) -> AsyncGenerator[str, None]:
    """Stream journalctl -f output as SSE events."""
    proc = await asyncio.create_subprocess_exec(
        "journalctl",
        "--user",
        "-u",
        unit,
        "-n",
        str(n),
        "-f",
        "--no-pager",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        async for line in proc.stdout:
            text = line.decode().rstrip()
            yield f"data: {text}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        proc.kill()
        await proc.wait()
