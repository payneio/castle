"""castle create - scaffold a new project from templates."""

from __future__ import annotations

import argparse

from castle_cli.config import load_config, save_config
from castle_cli.manifest import (
    CaddySpec,
    ComponentManifest,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    InstallSpec,
    ManageSpec,
    PathInstallSpec,
    ProxySpec,
    RunPythonUvTool,
    SystemdSpec,
    ToolSpec,
)
from castle_cli.templates.scaffold import scaffold_project


def next_available_port(config: object) -> int:
    """Find the next available port starting from 9001 (9000 is reserved for gateway)."""
    used_ports = set()
    for manifest in config.components.values():
        if manifest.expose and manifest.expose.http:
            used_ports.add(manifest.expose.http.internal.port)
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

    if name in config.components:
        print(f"Error: component '{name}' already exists in castle.yaml")
        return 1

    project_dir = config.root / name
    if project_dir.exists():
        print(f"Error: directory '{name}' already exists")
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

    # Build manifest entry
    env_prefix = package_name.upper()

    if proj_type == "service":
        manifest = ComponentManifest(
            id=name,
            description=args.description or f"A castle {proj_type}",
            run=RunPythonUvTool(
                runner="python_uv_tool",
                tool=name,
                cwd=name,
                env={f"{env_prefix}_DATA_DIR": f"/data/castle/{name}"},
            ),
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
        manifest = ComponentManifest(
            id=name,
            description=args.description or f"A castle {proj_type}",
            tool=ToolSpec(source=f"{name}/"),
            install=InstallSpec(path=PathInstallSpec(alias=name)),
        )
    else:
        # library or other
        manifest = ComponentManifest(
            id=name,
            description=args.description or f"A castle {proj_type}",
        )

    config.components[name] = manifest
    save_config(config)

    print(f"Created {proj_type} '{name}' at {project_dir}")
    if port:
        print(f"  Port: {port}")
    print("  Registered in castle.yaml")
    print("\nNext steps:")
    print(f"  cd {name}")
    print("  uv sync")
    if proj_type == "service":
        print(f"  uv run {name}  # starts on port {port}")
    print(f"  castle test {name}")

    return 0


