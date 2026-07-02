"""castle run - run a program or service in the foreground.

Unified: if the target is a program with a declared `run` command, run that in
the foreground (dev-run). Otherwise fall back to the deployed-service run from
the registry.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from castle_core.generators.systemd import secret_env_path
from castle_core.registry import REGISTRY_PATH, load_registry

from castle_cli.config import load_config


def _load_secret_env(name: str) -> dict[str, str]:
    """Read a deployment's generated secret env file (KEY=value lines), if any.

    Secrets are kept out of the registry, so a foreground run merges them from the
    file systemd/docker would otherwise load, matching the deployed environment.
    """
    path = secret_env_path(name)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            out[key] = val
    return out


def _run_program(name: str, extra: list[str]) -> int | None:
    """Run a program's declared `run` command in the foreground.

    Returns the exit code, or None if the program has no declared run command
    (so the caller can fall back to the deployed-service path).
    """
    config = load_config()
    prog = config.programs.get(name)
    if prog is None or prog.commands is None or prog.commands.run is None:
        return None
    if not prog.source:
        print(f"Error: program '{name}' has no source directory.")
        return 1
    cwd = Path(prog.source)
    cmds = prog.commands.run
    rc = 0
    for i, argv in enumerate(cmds):
        # Append extra args to the final command in the sequence.
        full = list(argv) + (extra if i == len(cmds) - 1 else [])
        print(f"Running {name}: {' '.join(full)}")
        rc = subprocess.run(full, cwd=cwd).returncode
        if rc != 0:
            break
    return rc


def run_run(args: argparse.Namespace) -> int:
    """Run a program's declared run, or a deployed service, in the foreground.

    Scoped by `resource`: `program run` runs the program's declared `run`;
    `service run` runs the deployed service's command from the registry.
    """
    name = args.name
    extra_args = getattr(args, "extra", []) or []
    resource = getattr(args, "resource", None)

    # Program: declared run command.
    if resource in (None, "program"):
        prog_rc = _run_program(name, extra_args)
        if prog_rc is not None:
            return prog_rc
        if resource == "program":
            print(f"Error: program '{name}' has no declared `run` command.")
            return 1

    # Service: deployed command from the registry.
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle apply' first.")
        return 1

    registry = load_registry()
    if name not in registry.deployed:
        print(f"Error: '{name}' is not a deployed service. Run 'castle apply' first.")
        return 1

    deployed = registry.deployed[name]
    cmd = list(deployed.run_cmd) + extra_args
    env = dict(os.environ)
    env.update(deployed.env)
    env.update(_load_secret_env(name))
    print(f"Running {name}: {' '.join(cmd)}")
    return subprocess.run(cmd, env=env).returncode
