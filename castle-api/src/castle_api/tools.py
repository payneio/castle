"""Tools router and program actions."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.manifest import ProgramSpec
from castle_core.stacks import available_actions, get_handler

from castle_api.config import get_config
from castle_api.models import ToolDetail, ToolSummary

router = APIRouter(tags=["tools"])


def _is_tool(comp: ProgramSpec) -> bool:
    """Check if a component is a tool."""
    return comp.behavior == "tool"


def _tool_summary(
    name: str, comp: ProgramSpec, root: Path | None = None
) -> ToolSummary:
    """Build a ToolSummary from a ProgramSpec that is a tool."""
    installed = shutil.which(name) is not None

    # Infer runner from source directory
    runner = None
    source = comp.source
    if source:
        source_dir = Path(source)
        if (source_dir / "pyproject.toml").exists():
            runner = "python"
        elif source_dir.is_file():
            runner = "command"

    return ToolSummary(
        id=name,
        description=comp.description,
        source=source,
        version=comp.version,
        runner=runner,
        system_dependencies=comp.system_dependencies,
        installed=installed,
    )


@router.get("/tools", response_model=list[ToolSummary])
def list_tools() -> list[ToolSummary]:
    """List all registered tools (requires repo access)."""
    config = get_config()
    tools = {k: v for k, v in config.programs.items() if _is_tool(v)}

    return sorted(
        [
            _tool_summary(name, comp, config.root)
            for name, comp in tools.items()
        ],
        key=lambda t: t.id,
    )


@router.get("/tools/{name}", response_model=ToolDetail)
def get_tool(name: str) -> ToolDetail:
    """Get detailed info for a single tool."""
    config = get_config()

    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component '{name}' not found",
        )

    comp = config.programs[name]
    if not _is_tool(comp):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{name}' is not a tool",
        )

    summary = _tool_summary(name, comp, config.root)
    return ToolDetail(**summary.model_dump())


# ---------------------------------------------------------------------------
# Unified program action endpoint
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {"build", "test", "lint", "type-check", "check", "install", "uninstall"}


@router.post("/programs/{name}/{action}")
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
