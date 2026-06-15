"""castle service create / castle job create — declare a deployment.

A service or job can run anything (a castle program or not). `--program`
records a convenience reference for description fallthrough; the run target is
the console script (python) or argv (command) to execute.
"""

from __future__ import annotations

import argparse

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    CaddySpec,
    DefaultsSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    JobSpec,
    ManageSpec,
    ProxySpec,
    RunCommand,
    RunPython,
    ServiceSpec,
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


def _run_spec(runner: str, target: str, name: str) -> RunPython | RunCommand:
    if runner == "command":
        return RunCommand(runner="command", argv=target.split() or [name])
    return RunPython(runner="python", program=target or name)


def _check_new(config: object, name: str, section: str) -> str | None:
    """Return an error message if the name can't be created, else None."""
    existing = getattr(config, section)
    if name in existing:
        return f"Error: {section[:-1]} '{name}' already exists."
    return None


def run_service_create(args: argparse.Namespace) -> int:
    """Create a service entry in castle.yaml."""
    config = load_config()
    name = args.name
    if err := _check_new(config, name, "services"):
        print(err)
        return 1

    run = _run_spec(args.runner, args.run or args.program or name, name)

    expose = None
    proxy = None
    if args.port is not None:
        expose = ExposeSpec(
            http=HttpExposeSpec(
                internal=HttpInternal(port=args.port),
                health_path=args.health,
            )
        )
        if not args.no_proxy:
            path = args.path
            if args.path:
                path = args.path if args.path.startswith("/") else f"/{args.path}"
            elif args.host:
                path = None
            else:
                path = f"/{name}"
            proxy = ProxySpec(caddy=CaddySpec(path_prefix=path, host=args.host))

    config.services[name] = ServiceSpec(
        id=name,
        program=args.program,
        description=args.description or None,
        run=run,
        expose=expose,
        proxy=proxy,
        manage=ManageSpec(systemd=SystemdSpec()),
        defaults=_defaults(args.env),
    )
    save_config(config)

    print(f"Created service '{name}'.")
    print(f"  runs:   {args.runner} ({args.run or args.program or name})")
    if expose:
        print(f"  port:   {args.port}")
    if proxy and proxy.caddy:
        if proxy.caddy.path_prefix:
            print(f"  proxy:  {proxy.caddy.path_prefix}")
        if proxy.caddy.host:
            print(f"  host:   {proxy.caddy.host}")
    print(f"\nNext: castle service deploy {name} && castle service start {name}")
    return 0


def run_job_create(args: argparse.Namespace) -> int:
    """Create a job entry in castle.yaml."""
    config = load_config()
    name = args.name
    if err := _check_new(config, name, "jobs"):
        print(err)
        return 1

    run = _run_spec(args.runner, args.run or args.program or name, name)

    config.jobs[name] = JobSpec(
        id=name,
        program=args.program,
        description=args.description or None,
        run=run,
        schedule=args.schedule,
        manage=ManageSpec(systemd=SystemdSpec()),
        defaults=_defaults(args.env),
    )
    save_config(config)

    print(f"Created job '{name}'.")
    print(f"  runs:     {args.runner} ({args.run or args.program or name})")
    print(f"  schedule: {args.schedule}")
    print(f"\nNext: castle job deploy {name} && castle job enable {name}")
    return 0
