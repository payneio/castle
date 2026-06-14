"""castle build/test/lint/type-check/check/run/install/uninstall — dev verbs.

Verbs resolve per-program: a declared command (manifest `commands:` / `build:`)
overrides the stack default, falling back to the stack handler, else unavailable.
"""

from __future__ import annotations

import argparse
import asyncio

from castle_core.stacks import is_available, run_action

from castle_cli.config import CastleConfig, load_config


def _run_verb(config: CastleConfig, project_name: str, verb: str) -> bool:
    """Run a verb for a single program. Returns True on success."""
    if project_name not in config.programs:
        print(f"Unknown program: {project_name}")
        return False

    comp = config.programs[project_name]
    if not comp.source:
        print(f"  {project_name}: no source directory, skipping")
        return True

    if not is_available(comp, verb):
        print(f"  {project_name}: '{verb}' not available (no declared command or stack), skipping")
        return True

    print(f"\n{'─' * 40}")
    print(f"  {verb}: {project_name}")
    print(f"{'─' * 40}")

    result = asyncio.run(run_action(verb, project_name, comp, config.root))
    if result.output:
        print(result.output)
    return result.status == "ok"


def _run_verb_all(config: CastleConfig, verb: str) -> bool:
    """Run a verb across every program that supports it. Returns True if all pass."""
    all_passed = True
    ran_any = False
    for name, comp in config.programs.items():
        if not comp.source or not is_available(comp, verb):
            continue
        ran_any = True
        if not _run_verb(config, name, verb):
            all_passed = False
    if not ran_any:
        print(f"No programs support '{verb}'.")
    return all_passed


def run_verb(args: argparse.Namespace, verb: str) -> int:
    """Generic entry point for a dev verb (single program or all)."""
    config = load_config()
    if getattr(args, "name", None):
        return 0 if _run_verb(config, args.name, verb) else 1
    ok = _run_verb_all(config, verb)
    print(f"\n{'All ' + verb + ' passed.' if ok else 'Some ' + verb + ' failed.'}")
    return 0 if ok else 1


# Thin named wrappers wired from main.py.
def run_test(args: argparse.Namespace) -> int:
    return run_verb(args, "test")


def run_lint(args: argparse.Namespace) -> int:
    return run_verb(args, "lint")


def run_format(args: argparse.Namespace) -> int:
    return run_verb(args, "format")


def run_build(args: argparse.Namespace) -> int:
    return run_verb(args, "build")


def run_type_check(args: argparse.Namespace) -> int:
    return run_verb(args, "type-check")


def run_check(args: argparse.Namespace) -> int:
    return run_verb(args, "check")


def _lifecycle(config: CastleConfig, name: str, deactivate: bool) -> bool:
    """Activate or deactivate a single program. Returns True on success."""
    from castle_core.lifecycle import activate
    from castle_core.lifecycle import deactivate as do_deactivate

    if name not in config.programs and name not in config.services and name not in config.jobs:
        print(f"Unknown program: {name}")
        return False
    verb = "deactivate" if deactivate else "activate"
    print(f"\n{'─' * 40}\n  {verb}: {name}\n{'─' * 40}")
    fn = do_deactivate if deactivate else activate
    result = asyncio.run(fn(name, config, config.root))
    if result.output:
        print(result.output)
    return result.status == "ok"


def run_install(args: argparse.Namespace) -> int:
    """Activate (install/deploy/serve) a program — verb word kept, meaning unified."""
    config = load_config()
    if getattr(args, "name", None):
        return 0 if _lifecycle(config, args.name, deactivate=False) else 1
    ok = all(
        _lifecycle(config, name, deactivate=False)
        for name, comp in config.programs.items()
        if comp.source
    )
    return 0 if ok else 1


def run_uninstall(args: argparse.Namespace) -> int:
    """Deactivate (uninstall/stop/unpublish) a program."""
    config = load_config()
    if getattr(args, "name", None):
        return 0 if _lifecycle(config, args.name, deactivate=True) else 1
    print("Refusing to deactivate all programs; name a target.")
    return 1
