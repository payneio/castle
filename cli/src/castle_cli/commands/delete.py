"""castle delete — remove a program/service/job from the registry.

Config-only by default (removes the castle.yaml entry; leaves source and any
installed binary in place). Use --source to also delete the source directory.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from castle_cli.config import load_config, save_config


def run_delete(args: argparse.Namespace) -> int:
    config = load_config()
    name = args.name
    resource = getattr(args, "resource", None)  # "program" | "service" | "job"

    # Resolve which sections this delete touches (scoped to one resource). Any
    # deployment resource name (service/job/tool/static/deployment) targets the
    # single deployments/ collection — the kind is derived, not a separate section.
    _DEPLOY_RESOURCES = (None, "service", "job", "tool", "static", "deployment")
    in_programs = name in config.programs and resource in (None, "program")
    in_deployment = name in config.deployments and resource in _DEPLOY_RESOURCES
    if not (in_programs or in_deployment):
        where = f" {resource}" if resource else ""
        print(f"Error: no{where} '{name}' in castle.yaml")
        return 1

    where = [s for s, present in
             (("program", in_programs), ("deployment", in_deployment)) if present]

    # A program can't be removed while a deployment still references it. A ref
    # named the same is removed in this call; any other referencing deployment
    # would be left dangling, so refuse.
    if in_programs:
        dangling = [
            d for d, spec in config.deployments.items()
            if spec.program == name and not (d == name and in_deployment)
        ]
        if dangling:
            print(
                "Error: programs with active jobs or services cannot be removed.\n"
                f"  Delete these first: {', '.join(dangling)}"
            )
            return 1

    # Resolve source dir (from the program entry) for the optional --source removal.
    source_dir: Path | None = None
    if in_programs and config.programs[name].source:
        source_dir = Path(config.programs[name].source)

    print(f"Will remove '{name}' from castle.yaml ({', '.join(where)}).")
    if args.source and source_dir:
        print(f"Will ALSO delete source directory: {source_dir}")

    # Confirm unless --yes.
    if not args.yes:
        prompt = f"Delete '{name}'? [y/N] "
        try:
            if input(prompt).strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input). Re-run with --yes to confirm non-interactively.")
            return 1

    # Remove registry entries.
    if in_programs:
        del config.programs[name]
    if in_deployment:
        del config.deployments[name]
    save_config(config)
    print(f"Removed '{name}' from castle.yaml ({', '.join(where)}).")

    # Optional: delete the source directory.
    if args.source and source_dir:
        if source_dir.exists():
            shutil.rmtree(source_dir)
            print(f"Deleted source directory: {source_dir}")
        else:
            print(f"Source directory not found (already gone): {source_dir}")

    # Warn about runtime artifacts we did NOT touch.
    if in_deployment:
        print(
            f"\nNote: the systemd unit for '{name}' (if deployed) was NOT removed.\n"
            f"  Run: castle service disable {name}"
        )
    if shutil.which(name):
        print(
            f"\nNote: '{name}' is still installed on PATH. To remove it:\n"
            f"  castle uninstall {name}"
        )

    return 0
