"""castle program create — scaffold a new program from templates."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.config import REPOS_DIR, load_config, save_config
from castle_cli.manifest import (
    BuildSpec,
    CaddySpec,
    DefaultsSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ManageSpec,
    ProgramSpec,
    ProxySpec,
    RunPython,
    ServiceSpec,
    SystemdSpec,
)
from castle_cli.templates.scaffold import scaffold_project

# Stack determines default behavior and scaffold template
STACK_DEFAULTS: dict[str, str] = {
    "python-fastapi": "daemon",
    "python-cli": "tool",
    "react-vite": "frontend",
    "supabase": "frontend",
}

# Static build output per stack, for `behavior: frontend` programs. The gateway
# serves this dir in place at /<name>/ (no service, no process). A supabase app
# ships a raw `public/`; react-vite builds to `dist/`.
STACK_BUILD_OUTPUTS: dict[str, str] = {
    "supabase": "public",
    "react-vite": "dist",
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
    """Create a new project (scaffolded from a stack, or a bare program)."""
    config = load_config()
    name = args.name
    stack = args.stack
    behavior = STACK_DEFAULTS.get(stack) if stack else None

    if name in config.programs or name in config.services or name in config.jobs:
        print(f"Error: '{name}' already exists in castle.yaml")
        return 1

    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    project_dir = REPOS_DIR / name
    if project_dir.exists():
        print(f"Error: directory already exists: {project_dir}")
        return 1

    # Determine port for daemons
    port = args.port
    if behavior == "daemon" and port is None:
        port = next_available_port(config)

    package_name = name.replace("-", "_")
    description = args.description or (f"A castle {stack} program" if stack else f"{name}")

    if stack:
        scaffold_project(
            project_dir=project_dir,
            name=name,
            package_name=package_name,
            stack=stack,
            description=description,
            port=port,
        )
    else:
        # Bare program: empty source tree, no scaffold; user declares commands later.
        project_dir.mkdir(parents=True)

    # Initialize a git repo for the new source.
    subprocess.run(["git", "init", "-q", str(project_dir)], check=False)

    # Frontend stacks with a static output get a build spec so the gateway emits
    # an in-place static route at /<name>/ (no service, no process).
    build = None
    if stack in STACK_BUILD_OUTPUTS:
        build = BuildSpec(outputs=[STACK_BUILD_OUTPUTS[stack]])

    config.programs[name] = ProgramSpec(
        id=name,
        description=description,
        source=str(project_dir),
        stack=stack,
        behavior=behavior,
        build=build,
    )
    if behavior == "daemon":
        prefix = name.replace("-", "_").upper()
        config.services[name] = ServiceSpec(
            id=name,
            program=name,
            run=RunPython(runner="python", program=name),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=port),
                    health_path="/health",
                )
            ),
            proxy=ProxySpec(caddy=CaddySpec()),  # expose at <name>.<gateway.domain>
            manage=ManageSpec(systemd=SystemdSpec()),
            # python-fastapi scaffold reads env_prefix MY_SERVICE_ — map castle's
            # computed port/data dir to those vars (explicit, no hidden injection).
            defaults=DefaultsSpec(
                env={f"{prefix}_PORT": "${port}", f"{prefix}_DATA_DIR": "${data_dir}"}
            ),
        )

    save_config(config)

    label = f"{stack} program" if stack else "bare program"
    print(f"Created {label} '{name}' at {project_dir}")
    if port:
        print(f"  Port: {port}")
    print("  Registered in castle.yaml")
    print("\nNext steps:")
    print(f"  cd {project_dir}")
    if stack == "supabase":
        print("  # edit migrations/, functions/, public/ — targets the shared substrate")
        print(f"  castle program build {name}   # apply migrations to the substrate")
        print(f"  castle deploy && castle gateway reload   # serve at /{name}/")
    elif stack:
        print("  uv sync")
        if behavior == "daemon":
            print(f"  uv run {name}  # starts on port {port}")
            print(f"  castle deploy {name}")
        print(f"  castle test {name}")
    else:
        print("  # add code, then declare commands: in castle.yaml")

    return 0
