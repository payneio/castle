"""castle logs - view component logs."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.commands.service import UNIT_PREFIX
from castle_cli.config import load_config


def run_logs(args: argparse.Namespace) -> int:
    """View logs for a component."""
    config = load_config()
    name = args.name

    if name not in config.components:
        print(f"Error: component '{name}' not found in castle.yaml")
        return 1

    manifest = config.components[name]

    # Container logs
    if manifest.run and manifest.run.runner == "container":
        return _container_logs(name, args)

    # Systemd logs (default for managed services)
    if manifest.manage and manifest.manage.systemd:
        return _systemd_logs(name, args)

    print(f"Error: '{name}' has no log source (not systemd-managed or containerized)")
    return 1


def _systemd_logs(name: str, args: argparse.Namespace) -> int:
    """Show journalctl logs for a systemd service."""
    unit_name = f"{UNIT_PREFIX}{name}.service"
    cmd = ["journalctl", "--user", "-u", unit_name]

    lines = getattr(args, "lines", 50)
    if lines:
        cmd.extend(["-n", str(lines)])

    if getattr(args, "follow", False):
        cmd.append("-f")

    result = subprocess.run(cmd)
    return result.returncode


def _container_logs(name: str, args: argparse.Namespace) -> int:
    """Show container logs."""
    import shutil

    runtime = shutil.which("podman") or shutil.which("docker") or "podman"
    container_name = f"castle-{name}"
    cmd = [runtime, "logs"]

    lines = getattr(args, "lines", 50)
    if lines:
        cmd.extend(["--tail", str(lines)])

    if getattr(args, "follow", False):
        cmd.append("-f")

    cmd.append(container_name)

    result = subprocess.run(cmd)
    return result.returncode
