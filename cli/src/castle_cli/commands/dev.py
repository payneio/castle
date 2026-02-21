"""castle test / castle lint - run dev commands across projects."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from castle_cli.config import CastleConfig, load_config


def _get_project_dir(config: CastleConfig, project_name: str) -> Path:
    """Get the directory for a component."""
    if project_name not in config.components:
        raise ValueError(f"Unknown component: {project_name}")
    manifest = config.components[project_name]
    cwd = manifest.run.cwd if manifest.run else None
    working_dir = cwd or project_name
    return config.root / working_dir


def _has_pyproject(project_dir: Path) -> bool:
    """Check if a project directory has a pyproject.toml."""
    return (project_dir / "pyproject.toml").exists()


def _run_in_project(
    project_dir: Path, cmd: list[str], label: str
) -> bool:
    """Run a command in a project directory. Returns True on success."""
    if not _has_pyproject(project_dir):
        return True  # Skip projects without pyproject.toml

    print(f"\n{'─' * 40}")
    print(f"  {label}: {project_dir.name}")
    print(f"{'─' * 40}")

    result = subprocess.run(cmd, cwd=project_dir)
    return result.returncode == 0


def run_test(args: argparse.Namespace) -> int:
    """Run tests for one or all projects."""
    config = load_config()

    if args.project:
        project_dir = _get_project_dir(config, args.project)
        tests_dir = project_dir / "tests"
        if not tests_dir.exists():
            print(f"No tests directory found for {args.project}")
            return 1
        success = _run_in_project(
            project_dir,
            ["uv", "run", "pytest", "tests/", "-v"],
            "Testing",
        )
        return 0 if success else 1

    # Run all
    all_passed = True
    for name, manifest in config.components.items():
        cwd = manifest.run.cwd if manifest.run else None
        working_dir = cwd or name
        project_dir = config.root / working_dir
        tests_dir = project_dir / "tests"
        if not tests_dir.exists():
            continue
        if not _has_pyproject(project_dir):
            continue
        success = _run_in_project(
            project_dir,
            ["uv", "run", "pytest", "tests/", "-v"],
            "Testing",
        )
        if not success:
            all_passed = False

    if all_passed:
        print("\nAll tests passed.")
    else:
        print("\nSome tests failed.")
    return 0 if all_passed else 1


def run_lint(args: argparse.Namespace) -> int:
    """Run linter for one or all projects."""
    config = load_config()

    if args.project:
        project_dir = _get_project_dir(config, args.project)
        success = _run_in_project(
            project_dir,
            ["uv", "run", "ruff", "check", "."],
            "Linting",
        )
        return 0 if success else 1

    # Run all
    all_passed = True
    for name, manifest in config.components.items():
        cwd = manifest.run.cwd if manifest.run else None
        working_dir = cwd or name
        project_dir = config.root / working_dir
        if not _has_pyproject(project_dir):
            continue
        success = _run_in_project(
            project_dir,
            ["uv", "run", "ruff", "check", "."],
            "Linting",
        )
        if not success:
            all_passed = False

    if all_passed:
        print("\nAll lint checks passed.")
    else:
        print("\nSome lint checks failed.")
    return 0 if all_passed else 1
