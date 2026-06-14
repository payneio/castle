"""castle deploy — thin CLI wrapper around castle_core.deploy."""

from __future__ import annotations

import argparse

from castle_core.deploy import deploy


def run_deploy(args: argparse.Namespace) -> int:
    """Deploy from castle.yaml to ~/.castle/."""
    target_name = getattr(args, "name", None)
    result = deploy(target_name=target_name)

    for msg in result.messages:
        print(f"  {msg}")

    print(f"\nDeployed {result.deployed_count} item(s).")
    if result.deployed_count > 0:
        print("Run 'castle start' to start all services.")
    return 0
