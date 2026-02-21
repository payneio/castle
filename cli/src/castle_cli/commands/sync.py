"""castle sync - sync submodules and install dependencies."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from castle_cli.config import ensure_dirs, load_config
from castle_cli.manifest import ToolType


def run_sync(args: argparse.Namespace) -> int:
    """Sync submodules and install dependencies in all projects."""
    config = load_config()
    ensure_dirs()

    # Update git submodules
    print("Updating git submodules...")
    result = subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=config.root,
    )
    if result.returncode != 0:
        print("Warning: git submodule update failed (may not be a git repo)")

    # Run uv sync in each project that has a pyproject.toml
    all_ok = True
    synced_dirs: set[Path] = set()
    for name, manifest in config.components.items():
        cwd = manifest.run.cwd if manifest.run else None
        working_dir = cwd or name
        project_dir = config.root / working_dir
        pyproject = project_dir / "pyproject.toml"

        if not pyproject.exists() or project_dir in synced_dirs:
            continue

        print(f"\nSyncing {name}...")
        result = subprocess.run(["uv", "sync"], cwd=project_dir)
        if result.returncode != 0:
            print(f"  Warning: uv sync failed for {name}")
            all_ok = False
        else:
            print("  OK")
        synced_dirs.add(project_dir)

    # Install tools by type
    uv_path = shutil.which("uv") or "uv"
    installed_dirs: set[Path] = set()

    for name, manifest in config.components.items():
        if not manifest.tool:
            continue

        if manifest.tool.tool_type == ToolType.PYTHON_STANDALONE:
            source = manifest.tool.source
            if not source:
                continue
            project_dir = config.root / source
            if not (project_dir / "pyproject.toml").exists():
                continue
            if project_dir in installed_dirs:
                continue
            print(f"\nInstalling {name}...")
            result = subprocess.run(
                [uv_path, "tool", "install", "--editable", str(project_dir),
                 "--force"],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                if "already installed" in result.stderr.lower():
                    print(f"  {name}: already installed")
                else:
                    print(f"  Warning: {result.stderr.strip()}")
                    all_ok = False
            else:
                print(f"  {name}: OK")
            installed_dirs.add(project_dir)

        elif manifest.tool.tool_type == ToolType.SCRIPT:
            # Verify script tools are accessible
            alias = name
            if manifest.install and manifest.install.path and manifest.install.path.alias:
                alias = manifest.install.path.alias
            if not shutil.which(alias):
                source = manifest.tool.source
                if source:
                    script_path = config.root / source
                    if script_path.exists():
                        link = Path.home() / ".local" / "bin" / alias
                        link.parent.mkdir(parents=True, exist_ok=True)
                        if not link.exists():
                            link.symlink_to(script_path)
                            print(f"\n  Linked {alias} → {script_path}")

    if all_ok:
        print("\nAll projects synced.")
    else:
        print("\nSync completed with warnings.")

    return 0
