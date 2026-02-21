"""Tools router — browse and inspect tool components."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_cli.config import load_config
from castle_cli.manifest import ComponentManifest

from castle_api.config import settings
from castle_api.models import ToolCategory, ToolDetail, ToolSummary

router = APIRouter(tags=["tools"])


def _tool_summary(name: str, manifest: ComponentManifest, root: Path | None = None) -> ToolSummary:
    """Build a ToolSummary from a manifest that has a tool spec."""
    t = manifest.tool
    assert t is not None
    installed = bool(manifest.install and manifest.install.path and manifest.install.path.enable)

    # Infer runner from run block or source directory
    runner = manifest.run.runner if manifest.run else None
    if runner is None and t.source and root:
        source_dir = root / t.source
        if (source_dir / "pyproject.toml").exists():
            runner = "python_uv_tool"
        elif source_dir.is_file():
            runner = "command"

    return ToolSummary(
        id=name,
        description=manifest.description,
        source=t.source,
        version=t.version,
        runner=runner,
        system_dependencies=t.system_dependencies,
        installed=installed,
    )


def _find_md_for_tool(
    root: Path,
    source: str,
    tool_name: str,
) -> Path | None:
    """Find the .md documentation file for a tool source path."""
    source_path = root / source
    if source_path.is_file():
        md = source_path.with_suffix(".md")
        if md.exists():
            return md
    elif source_path.is_dir():
        py_name = tool_name.replace("-", "_")
        pkg_name = source_path.name
        md = source_path / "src" / pkg_name / f"{py_name}.md"
        if md.exists():
            return md
    return None


def _strip_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content."""
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            content = content[end + 5:]
    return content.strip()


@router.get("/tools", response_model=list[ToolCategory])
def list_tools() -> list[ToolCategory]:
    """List tools grouped by source directory."""
    config = load_config(settings.castle_root)
    tools = {k: v for k, v in config.components.items() if v.tool}

    by_group: dict[str, list[ToolSummary]] = {}
    for name, manifest in tools.items():
        t = manifest.tool
        assert t is not None
        if t.source:
            group = Path(t.source).name
        else:
            group = "standalone"
        by_group.setdefault(group, []).append(_tool_summary(name, manifest, config.root))

    return [
        ToolCategory(name=group, tools=sorted(items, key=lambda t: t.id))
        for group, items in sorted(by_group.items())
    ]


@router.get("/tools/{name}", response_model=ToolDetail)
def get_tool(name: str) -> ToolDetail:
    """Get detailed info for a single tool."""
    config = load_config(settings.castle_root)

    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component '{name}' not found",
        )

    manifest = config.components[name]
    if not manifest.tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{name}' is not a tool",
        )

    summary = _tool_summary(name, manifest, config.root)
    docs: str | None = None
    t = manifest.tool
    if t.source:
        md_path = _find_md_for_tool(config.root, t.source, name)
        if md_path and md_path.exists():
            docs = _strip_frontmatter(md_path.read_text())
            if not docs:
                docs = None

    return ToolDetail(**summary.model_dump(), docs=docs)


@router.post("/tools/{name}/install")
async def install_tool(name: str) -> dict:
    """Install a tool to PATH via uv tool install."""
    config = load_config(settings.castle_root)
    if name not in config.components:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found")

    manifest = config.components[name]
    if not manifest.tool or not manifest.tool.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no tool source to install")

    source_dir = config.root / manifest.tool.source
    if not (source_dir / "pyproject.toml").exists():
        raise HTTPException(status_code=400, detail=f"No pyproject.toml in {manifest.tool.source}")

    proc = await asyncio.create_subprocess_exec(
        "uv", "tool", "install", "--editable", str(source_dir), "--force",
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
    config = load_config(settings.castle_root)
    if name not in config.components:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found")

    manifest = config.components[name]
    if not manifest.tool or not manifest.tool.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no tool source")

    # uv tool uninstall uses the package name from pyproject.toml
    source_dir = config.root / manifest.tool.source
    # Try to read the package name; fall back to the source dir name
    pkg_name = source_dir.name
    pyproject = source_dir / "pyproject.toml"
    if pyproject.exists():
        import tomllib
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        pkg_name = data.get("project", {}).get("name", pkg_name)

    proc = await asyncio.create_subprocess_exec(
        "uv", "tool", "uninstall", pkg_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (stdout or stderr or b"").decode().strip()

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=output or "Uninstall failed")

    return {"component": name, "action": "uninstall", "status": "ok"}
