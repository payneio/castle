"""castle sync - sync submodules and install dependencies."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from castle_cli.config import ensure_dirs, load_config
from castle_cli.manifest import ComponentManifest


def _sync_cmd(manifest: ComponentManifest) -> list[str] | None:
    """Derive the sync command from the manifest's runner."""
    run = manifest.run
    if run is None:
        # No runner — check for build commands (frontends)
        if manifest.build and manifest.build.commands:
            # Frontends declare build commands; infer from source dir at call site
            return None
        return None

    match run.runner:
        case "python_uv_tool" | "python_module":
            return ["uv", "sync"]
        case "node":
            return [run.package_manager, "install"]
        case _:
            return None


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

    # Sync dependencies in each project
    all_ok = True
    synced_dirs: set[Path] = set()
    for name, manifest in config.components.items():
        source_dir = manifest.source_dir
        if not source_dir:
            continue
        project_dir = config.root / source_dir

        if project_dir in synced_dirs or not project_dir.is_dir():
            continue

        cmd = _sync_cmd(manifest)
        if cmd is None:
            # No runner — check if it's a frontend with a package.json
            if manifest.build and (project_dir / "package.json").exists():
                pm = "pnpm" if (project_dir / "pnpm-lock.yaml").exists() else "npm"
                cmd = [pm, "install"]
            else:
                continue

        label = cmd[0]
        print(f"\nSyncing {name} ({label})...")
        result = subprocess.run(cmd, cwd=project_dir)
        if result.returncode != 0:
            print(f"  Warning: sync failed for {name}")
            all_ok = False
        else:
            print("  OK")
        synced_dirs.add(project_dir)

    # Install components as uv tools or symlinks
    uv_path = shutil.which("uv") or "uv"
    installed_dirs: set[Path] = set()

    for name, manifest in config.components.items():
        # Determine source directory — from tool.source or manifest.source
        source = None
        if manifest.tool and manifest.tool.source:
            source = manifest.tool.source
        elif manifest.run and manifest.run.runner == "python_uv_tool" and manifest.source_dir:
            source = manifest.source_dir

        if not source:
            continue

        source_dir = config.root / source

        if (source_dir / "pyproject.toml").exists():
            # Python package — uv tool install
            if source_dir in installed_dirs:
                continue
            print(f"\nInstalling {name}...")
            result = subprocess.run(
                [uv_path, "tool", "install", "--editable", str(source_dir), "--force"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                if "already installed" in result.stderr.lower():
                    print(f"  {name}: already installed")
                else:
                    print(f"  Warning: {result.stderr.strip()}")
                    all_ok = False
            else:
                print(f"  {name}: OK")
            installed_dirs.add(source_dir)

        elif source_dir.is_file():
            # Script file — symlink to ~/.local/bin/
            alias = name
            if manifest.install and manifest.install.path and manifest.install.path.alias:
                alias = manifest.install.path.alias
            if not shutil.which(alias):
                link = Path.home() / ".local" / "bin" / alias
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists():
                    link.symlink_to(source_dir)
                    print(f"\n  Linked {alias} → {source_dir}")

    if all_ok:
        print("\nAll projects synced.")
    else:
        print("\nSync completed with warnings.")

    return 0
