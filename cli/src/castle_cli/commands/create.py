"""castle create - scaffold a new project from templates."""

from __future__ import annotations

import argparse

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    CaddySpec,
    ProgramSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    InstallSpec,
    ManageSpec,
    PathInstallSpec,
    ProxySpec,
    RunPython,
    ServiceSpec,
    SystemdSpec,
    ToolSpec,
)
from castle_cli.templates.scaffold import scaffold_project

# Stack determines default behavior and scaffold template
STACK_DEFAULTS: dict[str, str] = {
    "python-fastapi": "daemon",
    "python-cli": "tool",
    "react-vite": "frontend",
}


def next_available_port(config: object) -> int:
    """Find the next available port starting from 9001 (9000 is reserved for gateway)."""
    used_ports = set()
    for svc in config.services.values():
        if svc.expose and svc.expose.http:
            used_ports.add(svc.expose.http.internal.port)
    # Also reserve gateway port
    used_ports.add(config.gateway.port)

    port = 9001
    while port in used_ports:
        port += 1
    return port


def run_create(args: argparse.Namespace) -> int:
    """Create a new project."""
    config = load_config()
    name = args.name
    stack = args.stack
    behavior = STACK_DEFAULTS.get(stack)

    if name in config.programs or name in config.services or name in config.jobs:
        print(f"Error: '{name}' already exists in castle.yaml")
        return 1

    programs_dir = config.root / "programs"
    programs_dir.mkdir(exist_ok=True)
    project_dir = programs_dir / name
    if project_dir.exists():
        print(f"Error: directory 'programs/{name}' already exists")
        return 1

    # Determine port for daemons
    port = args.port
    if behavior == "daemon" and port is None:
        port = next_available_port(config)

    # Package name: convert kebab-case to snake_case
    package_name = name.replace("-", "_")

    # Scaffold the project files
    scaffold_project(
        project_dir=project_dir,
        name=name,
        package_name=package_name,
        stack=stack,
        description=args.description or f"A castle {stack} program",
        port=port,
    )

    # Build entries
    if behavior == "daemon":
        # Program for software identity
        config.programs[name] = ProgramSpec(
            id=name,
            description=args.description or f"A castle {stack} program",
            source=f"programs/{name}",
            stack=stack,
        )
        # Service for deployment
        config.services[name] = ServiceSpec(
            id=name,
            component=name,
            run=RunPython(runner="python", tool=name),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=port),
                    health_path="/health",
                )
            ),
            proxy=ProxySpec(caddy=CaddySpec(path_prefix=f"/{name}")),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
    elif behavior == "tool":
        config.programs[name] = ProgramSpec(
            id=name,
            description=args.description or f"A castle {stack} program",
            source=f"programs/{name}",
            stack=stack,
            tool=ToolSpec(),
            install=InstallSpec(path=PathInstallSpec(alias=name)),
        )
    else:
        # frontend or other
        config.programs[name] = ProgramSpec(
            id=name,
            description=args.description or f"A castle {stack} program",
            source=f"programs/{name}",
            stack=stack,
        )

    save_config(config)

    print(f"Created {stack} program '{name}' at {project_dir}")
    if port:
        print(f"  Port: {port}")
    print("  Registered in castle.yaml")
    print("\nNext steps:")
    print(f"  cd programs/{name}")
    print("  uv sync")
    if behavior == "daemon":
        print(f"  uv run {name}  # starts on port {port}")
        print(f"  castle deploy {name}  # deploy to ~/.castle/")
    print(f"  castle test {name}")

    return 0
