"""castle service create / castle job create — declare a deployment.

A service or job can run anything (a castle program or not). `--program`
records a convenience reference for description fallthrough; the run target is
the console script (python) or argv (command) to execute.
"""

from __future__ import annotations

import argparse

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    DefaultsSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ManageSpec,
    Reach,
    RunCommand,
    RunPython,
    SystemdDeployment,
    SystemdSpec,
)


def _defaults(env_args: list[str] | None) -> DefaultsSpec | None:
    """Parse repeated --env KEY=VALUE into a DefaultsSpec, or None."""
    if not env_args:
        return None
    env: dict[str, str] = {}
    for item in env_args:
        key, _, value = item.partition("=")
        env[key.strip()] = value
    return DefaultsSpec(env=env)


def _run_spec(launcher: str, target: str, name: str) -> RunPython | RunCommand:
    if launcher == "command":
        return RunCommand(launcher="command", argv=target.split() or [name])
    return RunPython(launcher="python", program=target or name)


def _check_new(config: object, name: str, label: str) -> str | None:
    """Return an error message if the deployment name is taken, else None."""
    if config.deployments_named(name):
        return f"Error: {label} '{name}' already exists."
    return None


def run_service_create(args: argparse.Namespace) -> int:
    """Create a service entry in castle.yaml."""
    config = load_config()
    name = args.name
    if err := _check_new(config, name, "service"):
        print(err)
        return 1

    run = _run_spec(args.launcher, args.run or args.program or name, name)

    expose = None
    reach = Reach.OFF
    if args.port is not None:
        expose = ExposeSpec(
            http=HttpExposeSpec(
                internal=HttpInternal(port=args.port),
                health_path=args.health,
            )
        )
        # Expose at <name>.<gateway.domain> (the subdomain is the service name).
        reach = Reach.OFF if args.no_proxy else Reach.INTERNAL

    config.services[name] = SystemdDeployment(
        id=name,
        manager="systemd",
        program=args.program,
        description=args.description or None,
        run=run,
        expose=expose,
        reach=reach,
        manage=ManageSpec(systemd=SystemdSpec()),
        defaults=_defaults(args.env),
    )
    save_config(config)

    print(f"Created service '{name}'.")
    print(f"  runs:   {args.launcher} ({args.run or args.program or name})")
    if expose:
        print(f"  port:   {args.port}")
    if reach != Reach.OFF:
        print(f"  subdomain: {name}.<gateway.domain>")
    print(f"\nNext: castle apply {name}")
    return 0


def run_job_create(args: argparse.Namespace) -> int:
    """Create a job entry in castle.yaml."""
    config = load_config()
    name = args.name
    if err := _check_new(config, name, "job"):
        print(err)
        return 1

    run = _run_spec(args.launcher, args.run or args.program or name, name)

    # A job is a systemd deployment with a schedule (→ a .timer).
    config.jobs[name] = SystemdDeployment(
        id=name,
        manager="systemd",
        program=args.program,
        description=args.description or None,
        run=run,
        schedule=args.schedule,
        manage=ManageSpec(systemd=SystemdSpec()),
        defaults=_defaults(args.env),
    )
    save_config(config)

    print(f"Created job '{name}'.")
    print(f"  runs:     {args.launcher} ({args.run or args.program or name})")
    print(f"  schedule: {args.schedule}")
    print(f"\nNext: castle apply {name}")
    return 0
