"""castle run - run a component in the foreground."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from castle_cli.config import load_config, resolve_env_vars


def run_run(args: argparse.Namespace) -> int:
    """Run a component in the foreground (dev mode)."""
    config = load_config()
    name = args.name

    if name not in config.components:
        print(f"Error: component '{name}' not found in castle.yaml")
        return 1

    manifest = config.components[name]
    run = manifest.run

    if run is None:
        print(f"Error: component '{name}' has no run spec")
        return 1

    # Build command
    extra_args = getattr(args, "extra", []) or []
    cmd = _build_command(run, extra_args)
    if cmd is None:
        print(f"Error: unsupported runner '{run.runner}' for foreground execution")
        return 1

    # Working directory
    cwd = config.root / (run.working_dir or name)
    if not cwd.exists():
        print(f"Error: working directory '{cwd}' does not exist")
        return 1

    # Merge environment
    env = dict(os.environ)
    resolved = resolve_env_vars(run.env, manifest)
    env.update(resolved)

    # Run in foreground
    result = subprocess.run(cmd, cwd=cwd, env=env)
    return result.returncode


def _build_command(run: object, extra_args: list[str]) -> list[str] | None:
    """Build command list from RunSpec."""
    match run.runner:
        case "python_uv_tool":
            uv = shutil.which("uv") or "uv"
            cmd = [uv, "run", run.tool]
            cmd.extend(run.args)
            cmd.extend(extra_args)
            return cmd
        case "python_module":
            python = run.python or sys.executable
            cmd = [python, "-m", run.module]
            cmd.extend(run.args)
            cmd.extend(extra_args)
            return cmd
        case "command":
            cmd = list(run.argv)
            cmd.extend(extra_args)
            return cmd
        case "container":
            runtime = shutil.which("podman") or shutil.which("docker") or "podman"
            cmd = [runtime, "run", "--rm", "-it"]
            for cp, hp in run.ports.items():
                cmd.extend(["-p", f"{hp}:{cp}"])
            for vol in run.volumes:
                cmd.extend(["-v", vol])
            for key, val in run.env.items():
                cmd.extend(["-e", f"{key}={val}"])
            if run.workdir:
                cmd.extend(["-w", run.workdir])
            cmd.append(run.image)
            if run.command:
                cmd.extend(run.command)
            cmd.extend(run.args)
            cmd.extend(extra_args)
            return cmd
        case "node":
            pm = run.package_manager
            cmd = [pm, "run", run.script]
            cmd.extend(run.args)
            cmd.extend(extra_args)
            return cmd
        case _:
            return None
