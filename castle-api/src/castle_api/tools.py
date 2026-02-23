"""Tools router — browse and inspect tool components."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core.manifest import ComponentSpec

from castle_api.config import get_config
from castle_api.models import ToolDetail, ToolSummary

router = APIRouter(tags=["tools"])


def _is_tool(comp: ComponentSpec) -> bool:
    """Check if a component is a tool (has install.path or tool spec)."""
    return bool((comp.install and comp.install.path) or comp.tool)


def _tool_summary(
    name: str, comp: ComponentSpec, root: Path | None = None
) -> ToolSummary:
    """Build a ToolSummary from a ComponentSpec that is a tool."""
    t = comp.tool
    installed = bool(
        comp.install and comp.install.path and comp.install.path.enable
    )

    # Infer runner from source directory
    runner = None
    source = comp.source
    if source and root:
        source_dir = root / source
        if (source_dir / "pyproject.toml").exists():
            runner = "python"
        elif source_dir.is_file():
            runner = "command"

    return ToolSummary(
        id=name,
        description=comp.description,
        source=source,
        version=t.version if t else None,
        runner=runner,
        system_dependencies=t.system_dependencies if t else [],
        installed=installed,
    )


@router.get("/tools", response_model=list[ToolSummary])
def list_tools() -> list[ToolSummary]:
    """List all registered tools (requires repo access)."""
    config = get_config()
    tools = {k: v for k, v in config.components.items() if _is_tool(v)}

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

    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component '{name}' not found",
        )

    comp = config.components[name]
    if not _is_tool(comp):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{name}' is not a tool",
        )

    summary = _tool_summary(name, comp, config.root)
    return ToolDetail(**summary.model_dump())


@router.post("/tools/{name}/install")
async def install_tool(name: str) -> dict:
    """Install a tool to PATH via uv tool install."""
    config = get_config()
    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found"
        )

    comp = config.components[name]
    if not comp.source:
        raise HTTPException(
            status_code=400, detail=f"'{name}' has no source to install"
        )

    source_dir = config.root / comp.source
    if not (source_dir / "pyproject.toml").exists():
        raise HTTPException(
            status_code=400, detail=f"No pyproject.toml in {comp.source}"
        )

    proc = await asyncio.create_subprocess_exec(
        "uv",
        "tool",
        "install",
        "--editable",
        str(source_dir),
        "--force",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout or stderr or b"").decode().strip()

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=output or "Install failed")

    return {"component": name, "action": "install", "status": "ok"}


@router.post("/tools/{name}/uninstall")
async def uninstall_tool(name: str) -> dict:
    """Uninstall a tool from PATH via uv tool uninstall."""
    config = get_config()
    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found"
        )

    comp = config.components[name]
    if not comp.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no source")

    # uv tool uninstall uses the package name from pyproject.toml
    source_dir = config.root / comp.source
    pkg_name = source_dir.name
    pyproject = source_dir / "pyproject.toml"
    if pyproject.exists():
        import tomllib

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        pkg_name = data.get("project", {}).get("name", pkg_name)

    proc = await asyncio.create_subprocess_exec(
        "uv",
        "tool",
        "uninstall",
        pkg_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout or stderr or b"").decode().strip()

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=output or "Uninstall failed")

    return {"component": name, "action": "uninstall", "status": "ok"}
