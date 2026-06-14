"""castle expose — turn an existing program into a service.

`castle add` adopts source as a program; `castle expose` declares how to *run*
that program as a long-running systemd service (port, health, proxy). It fills
the gap where adopting a daemon left you with a program but no way to run it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    CaddySpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ManageSpec,
    ProxySpec,
    RunCommand,
    RunPython,
    ServiceSpec,
    SystemdSpec,
)


def _is_python(program: object) -> bool:
    """Whether the program runs as a python console script (uv-installed)."""
    stack = getattr(program, "stack", None)
    if stack and stack.startswith("python"):
        return True
    source = getattr(program, "source", None)
    return bool(source and (Path(source) / "pyproject.toml").exists())


def run_expose(args: argparse.Namespace) -> int:
    """Create a service entry that runs an existing program."""
    config = load_config()
    name = args.name

    program = config.programs.get(name)
    if program is None:
        print(f"Error: no program '{name}'. Adopt it first with 'castle add', then expose it.")
        return 1
    if name in config.services or name in config.jobs:
        print(f"Error: '{name}' is already a service or job.")
        return 1

    run_script = args.run or name
    run = (
        RunPython(runner="python", program=run_script)
        if _is_python(program)
        else RunCommand(runner="command", argv=[run_script])
    )

    expose = None
    proxy = None
    if args.port is not None:
        expose = ExposeSpec(
            http=HttpExposeSpec(
                internal=HttpInternal(port=args.port, port_env=args.port_env),
                health_path=args.health,
            )
        )
        host = getattr(args, "host", None)
        if not args.no_proxy:
            # A path prefix, a hostname, or both. With a host but no explicit
            # path, route by host only (root-based apps serve unchanged).
            if args.path:
                prefix = args.path if args.path.startswith("/") else "/" + args.path
            elif host:
                prefix = None
            else:
                prefix = f"/{name}"
            proxy = ProxySpec(caddy=CaddySpec(path_prefix=prefix, host=host))

    config.services[name] = ServiceSpec(
        id=name,
        program=name,
        run=run,
        expose=expose,
        proxy=proxy,
        manage=ManageSpec(systemd=SystemdSpec()),
    )
    save_config(config)

    print(f"Exposed '{name}' as a service.")
    print(f"  run:    {run.runner} ({run_script})")
    if expose:
        print(f"  port:   {args.port}" + (f"  (env: {args.port_env})" if args.port_env else ""))
        print(f"  health: {args.health}")
    if proxy and proxy.caddy:
        if proxy.caddy.path_prefix:
            print(f"  proxy:  {proxy.caddy.path_prefix}")
        if proxy.caddy.host:
            print(f"  host:   {proxy.caddy.host}")
    print("\nNext: castle deploy " + name + " && castle service enable " + name)
    return 0
