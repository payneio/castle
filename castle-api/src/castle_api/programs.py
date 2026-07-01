"""Program action endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from castle_core.stacks import available_actions, available_stacks, run_action

from castle_api.config import get_config

programs_router = APIRouter(tags=["programs"])


@programs_router.get("/stacks")
def list_stacks() -> list[str]:
    """Stack names castle has handlers for — populates the dashboard's stack select
    and keeps it in sync with the backend (no hardcoded frontend list)."""
    return available_stacks()

# ---------------------------------------------------------------------------
# Unified program action endpoint
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {
    "build",
    "test",
    "lint",
    "type-check",
    "check",
    "install",
    "uninstall",
}


@programs_router.post("/programs/{name}/{action}")
async def program_action(name: str, action: str) -> dict:
    """Run a lifecycle action on a program.

    Resolution-aware: a declared `commands:` entry overrides the stack default,
    so a program with no stack can still be linted/tested/built/installed.
    """
    if action not in _VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found"
        )

    comp = config.programs[name]
    if not comp.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no source directory")

    if action not in available_actions(comp):
        raise HTTPException(
            status_code=400,
            detail=f"Action '{action}' not available for '{name}' "
            f"(no declared command and no stack handler provides it)",
        )

    result = await run_action(action, name, comp, config.root)

    if result.status != "ok":
        raise HTTPException(status_code=500, detail=result.output or f"{action} failed")

    return {
        "program": result.program,
        "action": result.action,
        "status": result.status,
        "output": result.output,
    }
