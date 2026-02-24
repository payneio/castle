"""castle sync - sync submodules and install dependencies."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from castle_cli.config import ensure_dirs, load_config


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

    # Sync dependencies in each component's source directory
    all_ok = True
    synced_dirs: set[Path] = set()

    for name, comp in config.programs.items():
        source_dir = comp.source_dir
        if not source_dir:
            continue
        project_dir = config.root / source_dir

        if project_dir in synced_dirs or not project_dir.is_dir():
            continue

        # Determine sync command based on project type
        cmd = None
        if (project_dir / "pyproject.toml").exists():
            cmd = ["uv", "sync"]
        elif (project_dir / "package.json").exists():
            pm = "pnpm" if (project_dir / "pnpm-lock.yaml").exists() else "npm"
            cmd = [pm, "install"]

        if cmd is None:
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

    # Install components and python-runner services as uv tools
    uv_path = shutil.which("uv") or "uv"
    installed_dirs: set[Path] = set()

    # Install components with install.path
    for name, comp in config.programs.items():
        if not (comp.install and comp.install.path):
            continue
        source = comp.source_dir
        if not source:
            continue
        _try_install(config.root / source, name, comp, uv_path, installed_dirs)

    # Install python-runner services
    for name, svc in config.services.items():
        if svc.run.runner != "python":
            continue
        # Find source from component reference
        source = None
        if svc.component and svc.component in config.programs:
            source = config.programs[svc.component].source_dir
        if not source:
            continue
        source_dir = config.root / source
        if source_dir in installed_dirs:
            continue
        if (source_dir / "pyproject.toml").exists():
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

    if all_ok:
        print("\nAll projects synced.")
    else:
        print("\nSync completed with warnings.")

    return 0


def _try_install(
    source_dir: Path,
    name: str,
    comp: object,
    uv_path: str,
    installed_dirs: set[Path],
) -> bool:
    """Try to install a component. Returns True if installed."""
    if source_dir in installed_dirs:
        return False

    if (source_dir / "pyproject.toml").exists():
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
                return False
        else:
            print(f"  {name}: OK")
        installed_dirs.add(source_dir)
        return True

    elif source_dir.is_file():
        alias = name
        if comp.install and comp.install.path and comp.install.path.alias:
            alias = comp.install.path.alias
        if not shutil.which(alias):
            link = Path.home() / ".local" / "bin" / alias
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.exists():
                link.symlink_to(source_dir)
                print(f"\n  Linked {alias} → {source_dir}")
        return True

    return False
