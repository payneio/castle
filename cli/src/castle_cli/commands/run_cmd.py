"""castle run - run a component in the foreground."""

from __future__ import annotations

import argparse
import os
import subprocess

from castle_core.registry import REGISTRY_PATH, load_registry


def run_run(args: argparse.Namespace) -> int:
    """Run a component in the foreground using the registry."""
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return 1

    registry = load_registry()
    name = args.name

    if name not in registry.deployed:
        print(f"Error: component '{name}' not found in registry.")
        print("Run 'castle deploy' to update the registry.")
        return 1

    deployed = registry.deployed[name]

    # Build command with any extra args
    extra_args = getattr(args, "extra", []) or []
    cmd = list(deployed.run_cmd) + extra_args

    # Merge environment
    env = dict(os.environ)
    env.update(deployed.env)

    # Run in foreground (no cwd — registry-based, no repo dependency)
    print(f"Running {name}: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    return result.returncode
