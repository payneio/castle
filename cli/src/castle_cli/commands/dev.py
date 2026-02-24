"""castle test / castle lint - run dev commands across projects."""

from __future__ import annotations

import argparse
import asyncio

from castle_core.stacks import get_handler

from castle_cli.config import CastleConfig, load_config


def _run_action(config: CastleConfig, project_name: str, action: str) -> bool:
    """Run a stack action for a single project. Returns True on success."""
    if project_name not in config.programs:
        print(f"Unknown component: {project_name}")
        return False

    comp = config.programs[project_name]
    if not comp.source:
        print(f"  {project_name}: no source directory, skipping")
        return True

    handler = get_handler(comp.stack)
    if handler is None:
        print(f"  {project_name}: unsupported stack '{comp.stack}', skipping")
        return True

    method_name = action.replace("-", "_")
    method = getattr(handler, method_name, None)
    if method is None:
        print(f"  {project_name}: action '{action}' not supported")
        return False

    print(f"\n{'─' * 40}")
    print(f"  {action}: {project_name}")
    print(f"{'─' * 40}")

    result = asyncio.run(method(project_name, comp, config.root))
    if result.output:
        print(result.output)

    return result.status == "ok"


def run_test(args: argparse.Namespace) -> int:
    """Run tests for one or all projects."""
    config = load_config()

    if args.project:
        success = _run_action(config, args.project, "test")
        return 0 if success else 1

    # Run all
    all_passed = True
    for name, comp in config.programs.items():
        if not comp.source:
            continue
        handler = get_handler(comp.stack)
        if handler is None:
            continue
        # Skip projects without a tests directory (python) or test script (node)
        source_dir = config.root / comp.source
        if comp.stack in ("python-cli", "python-fastapi"):
            if not (source_dir / "tests").exists():
                continue
        if not _run_action(config, name, "test"):
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
        success = _run_action(config, args.project, "lint")
        return 0 if success else 1

    # Run all
    all_passed = True
    for name, comp in config.programs.items():
        if not comp.source:
            continue
        handler = get_handler(comp.stack)
        if handler is None:
            continue
        if not _run_action(config, name, "lint"):
            all_passed = False

    if all_passed:
        print("\nAll lint checks passed.")
    else:
        print("\nSome lint checks failed.")
    return 0 if all_passed else 1
