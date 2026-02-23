"""castle create - scaffold a new project from templates."""

from __future__ import annotations

import argparse

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    CaddySpec,
    ComponentSpec,
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
    proj_type = args.type

    if name in config.components or name in config.services or name in config.jobs:
        print(f"Error: '{name}' already exists in castle.yaml")
        return 1

    components_dir = config.root / "components"
    components_dir.mkdir(exist_ok=True)
    project_dir = components_dir / name
    if project_dir.exists():
        print(f"Error: directory 'components/{name}' already exists")
        return 1

    # Determine port for services
    port = args.port
    if proj_type == "service" and port is None:
        port = next_available_port(config)

    # Package name: convert kebab-case to snake_case
    package_name = name.replace("-", "_")

    # Scaffold the project files
    scaffold_project(
        project_dir=project_dir,
        name=name,
        package_name=package_name,
        proj_type=proj_type,
        description=args.description or f"A castle {proj_type}",
        port=port,
    )

    # Build entries
    if proj_type == "service":
        # Component for software identity
        config.components[name] = ComponentSpec(
            id=name,
            description=args.description or f"A castle {proj_type}",
            source=f"components/{name}",
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
    elif proj_type == "tool":
        config.components[name] = ComponentSpec(
            id=name,
            description=args.description or f"A castle {proj_type}",
            source=f"components/{name}",
            tool=ToolSpec(),
            install=InstallSpec(path=PathInstallSpec(alias=name)),
        )
    else:
        # library or other
        config.components[name] = ComponentSpec(
            id=name,
            description=args.description or f"A castle {proj_type}",
            source=f"components/{name}",
        )

    save_config(config)

    print(f"Created {proj_type} '{name}' at {project_dir}")
    if port:
        print(f"  Port: {port}")
    print("  Registered in castle.yaml")
    print("\nNext steps:")
    print(f"  cd components/{name}")
    print("  uv sync")
    if proj_type == "service":
        print(f"  uv run {name}  # starts on port {port}")
        print(f"  castle deploy {name}  # deploy to ~/.castle/")
    print(f"  castle test {name}")

    return 0
