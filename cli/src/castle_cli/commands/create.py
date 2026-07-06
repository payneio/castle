"""castle program create — scaffold a new program from templates."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.config import REPOS_DIR, load_config, save_config
from castle_cli.manifest import (
    BuildSpec,
    CaddyDeployment,
    DefaultsSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ManageSpec,
    PathDeployment,
    ProgramSpec,
    Requirement,
    RunPython,
    SystemdDeployment,
    SystemdSpec,
)
from castle_cli.templates.scaffold import scaffold_project

# Stack determines the default deployment kind + scaffold template.
STACK_DEFAULTS: dict[str, str] = {
    "python-fastapi": "service",
    "python-cli": "tool",
    "react-vite": "static",
    "supabase": "static",
}

# Static build output per stack, for `static` (caddy) deployments. The gateway
# serves this dir in place at <name>.<gateway.domain> (no service, no process).
# A supabase app ships a raw `public/`; react-vite builds to `dist/`.
STACK_BUILD_OUTPUTS: dict[str, str] = {
    "supabase": "public",
    "react-vite": "dist",
}

# Substrate a stack's apps depend on — seeded as a `requires` at creation so the
# relationship graph shows it. This keeps `stack` uncoupled from the runtime model:
# the stack declares the edge once here; the graph only ever reads the encoded
# `requires`, never the stack. See docs/relationships.md.
STACK_REQUIRES: dict[str, list[Requirement]] = {
    "supabase": [Requirement(kind="deployment", ref="supabase")],
}


def next_available_port(config: object) -> int:
    """Find the next available port starting from 9001 (9000 is reserved for gateway)."""
    used_ports = set()
    for _k, _n, dep in config.all_deployments():
        expose = getattr(dep, "expose", None)
        if expose and expose.http:
            used_ports.add(expose.http.internal.port)
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
    kind = STACK_DEFAULTS.get(stack) if stack else None

    if name in config.programs or config.deployments_named(name):
        print(f"Error: '{name}' already exists in castle.yaml")
        return 1

    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    project_dir = REPOS_DIR / name
    if project_dir.exists():
        print(f"Error: directory already exists: {project_dir}")
        return 1

    # Determine port for service (daemon) deployments
    port = args.port
    if kind == "service" and port is None:
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

    # Frontend stacks declare a build output; the program builds it, a `static`
    # service serves it in place at <name>.<gateway.domain>.
    build = None
    static_root = STACK_BUILD_OUTPUTS.get(stack)
    if static_root:
        build = BuildSpec(outputs=[static_root])

    # `kind` (and thus behavior) is derived from the deployment below — never
    # stored on the program.
    config.programs[name] = ProgramSpec(
        id=name,
        description=description,
        source=str(project_dir),
        stack=stack,
        build=build,
        # Seed the stack's substrate dependency (e.g. supabase) as a real `requires`.
        requires=list(STACK_REQUIRES.get(stack or "", [])),
    )
    if kind == "tool":
        # A PATH-managed deployment: installed via `uv tool install`, no unit/route.
        config.tools[name] = PathDeployment(
            id=name, manager="path", program=name, description=description
        )
    elif kind == "static":
        # A caddy-managed static deployment: no systemd unit, served from the build dir.
        config.statics[name] = CaddyDeployment(
            id=name,
            manager="caddy",
            program=name,
            root=static_root or "dist",
            description=description,
        )
    elif kind == "service":
        prefix = name.replace("-", "_").upper()
        config.services[name] = SystemdDeployment(
            id=name,
            manager="systemd",
            program=name,
            description=description,
            run=RunPython(launcher="python", program=name),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=port),
                    health_path="/health",
                )
            ),
            proxy=True,  # expose at <name>.<gateway.domain>
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
        print(f"  castle apply   # serve at {name}.<gateway.domain>")
    elif stack:
        print("  uv sync")
        if kind == "service":
            print(f"  uv run {name}  # starts on port {port}")
            print(f"  castle apply {name}")
        print(f"  castle test {name}")
    else:
        print("  # add code, then declare commands: in castle.yaml")

    return 0
