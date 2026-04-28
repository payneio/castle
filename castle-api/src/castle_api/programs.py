"""Program action endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from castle_core.stacks import available_actions, get_handler

from castle_api.config import get_config

programs_router = APIRouter(tags=["programs"])

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
    """Run a lifecycle action on a program via its stack handler."""
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

    actions = available_actions(comp)
    if action not in actions:
        raise HTTPException(
            status_code=400,
            detail=f"Action '{action}' not available for '{name}' (stack: {comp.stack})",
        )

    handler = get_handler(comp.stack)
    if handler is None:
        raise HTTPException(
            status_code=400, detail=f"No handler for stack '{comp.stack}'"
        )

    # Map hyphenated action names to method names (type-check → type_check)
    method_name = action.replace("-", "_")
    method = getattr(handler, method_name)

    result = await method(name, comp, config.root)

    if result.status != "ok":
        raise HTTPException(status_code=500, detail=result.output or f"{action} failed")

    return {
        "component": result.component,
        "action": result.action,
        "status": result.status,
        "output": result.output,
    }
