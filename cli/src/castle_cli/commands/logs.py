"""castle logs - view component logs."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.commands.service import UNIT_PREFIX
from castle_cli.config import load_config


def run_logs(args: argparse.Namespace) -> int:
    """View logs for a service or job."""
    config = load_config()
    name = args.name

    dep = config.deployments.get(name)
    if dep is not None and dep.manager == "systemd":
        if dep.run.launcher == "container":
            return _container_logs(name, args)
        if dep.run.launcher == "compose":
            return _compose_logs(name, dep, args)
        return _systemd_logs(name, args)

    if dep is not None:
        print(f"Error: '{name}' has no logs (manager: {dep.manager}).")
        return 1

    print(f"Error: '{name}' not found in deployments")
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


def _compose_logs(name: str, svc: object, args: argparse.Namespace) -> int:
    """Show aggregated logs for a compose-runner stack (by project label)."""
    import shutil

    runtime = shutil.which("docker") or shutil.which("podman") or "docker"
    project = getattr(svc.run, "project_name", None) or f"castle-{name}"  # type: ignore[attr-defined]
    cmd = [runtime, "compose", "-p", project, "logs"]

    lines = getattr(args, "lines", 50)
    if lines:
        cmd.extend(["--tail", str(lines)])

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
