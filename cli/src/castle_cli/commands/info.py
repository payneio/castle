"""castle info - show detailed program information."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from castle_cli.config import load_config

# Terminal colors
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"


def _load_deployed_program(name: str) -> object | None:
    """Try to load a specific deployed program from registry."""
    try:
        from castle_core.registry import load_registry

        registry = load_registry()
        return registry.deployed.get(name)
    except (FileNotFoundError, ValueError):
        return None


def run_info(args: argparse.Namespace) -> int:
    """Show detailed info for a program, service, or job."""
    config = load_config()
    name = args.name
    resource = getattr(args, "resource", None)

    # Look up in the requested section (or all, when unscoped).
    program = config.programs.get(name) if resource in (None, "program") else None
    service = config.services.get(name) if resource in (None, "service") else None
    job = config.jobs.get(name) if resource in (None, "job") else None

    if not program and not service and not job:
        where = f" {resource}" if resource else ""
        print(f"Error: no{where} '{name}' in castle.yaml")
        return 1

    deployed = _load_deployed_program(name)

    if getattr(args, "json", False):
        return _info_json(config, name, program, service, job, deployed)

    # Human-readable output
    print(f"\n{BOLD}{name}{RESET}")
    print(f"{'─' * 40}")

    # Determine kind(s) — for a program, the kinds of its deployments; for a
    # single deployment, its own kind.
    kinds: list[str] = []
    if program:
        kinds = sorted({k for _, k in config.deployments_of(name)})
    elif service:
        kinds = ["service"]
    elif job:
        kinds = ["job"]
    if kinds:
        label = "kind" if len(kinds) == 1 else "kinds"
        print(f"  {BOLD}{label}{RESET}:        {', '.join(kinds)}")

    # Show stack
    stack = None
    if program and program.stack:
        stack = program.stack
    elif service and service.program and service.program in config.programs:
        stack = config.programs[service.program].stack
    elif job and job.program and job.program in config.programs:
        stack = config.programs[job.program].stack
    if stack:
        print(f"  {BOLD}stack{RESET}:       {stack}")

    # Program info
    if program:
        if program.description:
            print(f"  {BOLD}description{RESET}: {program.description}")
        if program.source:
            print(f"  {BOLD}source{RESET}:      {program.source}")
        if program.system_dependencies:
            print(f"  {BOLD}requires{RESET}:    {', '.join(program.system_dependencies)}")
        if program.tags:
            print(f"  {BOLD}tags{RESET}:        {', '.join(program.tags)}")

    # Service info
    spec = service or job
    if spec:
        desc = spec.description
        if not desc and spec.program and spec.program in config.programs:
            desc = config.programs[spec.program].description
        if desc and not (program and program.description == desc):
            print(f"  {BOLD}description{RESET}: {desc}")
        if spec.program:
            print(f"  {BOLD}program{RESET}:     {spec.program}")

        # Launch spec
        print(f"  {BOLD}launcher{RESET}:    {spec.run.launcher}")
        if hasattr(spec.run, "program"):
            print(f"  {BOLD}program{RESET}:     {spec.run.program}")
        elif hasattr(spec.run, "argv"):
            print(f"  {BOLD}argv{RESET}:        {spec.run.argv}")
        elif hasattr(spec.run, "image"):
            print(f"  {BOLD}image{RESET}:       {spec.run.image}")

        # Defaults env
        if spec.defaults and spec.defaults.env:
            print(f"  {BOLD}defaults.env{RESET}:")
            for key, val in spec.defaults.env.items():
                print(f"    {key}: {val}")

    # Service-specific: expose, proxy, manage
    if service:
        if service.expose and service.expose.http:
            http = service.expose.http
            print(f"  {BOLD}port{RESET}:        {http.internal.port}")
            if http.health_path:
                print(f"  {BOLD}health{RESET}:      {http.health_path}")
        if service.proxy:
            print(f"  {BOLD}subdomain{RESET}:   {name}.<gateway.domain>")
        if service.manage and service.manage.systemd:
            sd = service.manage.systemd
            print(f"  {BOLD}systemd{RESET}:     enabled={sd.enable}, restart={sd.restart.value}")

    # Job-specific
    if job:
        print(f"  {BOLD}schedule{RESET}:    {job.schedule}")
        print(f"  {BOLD}timezone{RESET}:    {job.timezone}")

    # Deployed state from registry
    if deployed:
        print(f"\n  {GREEN}{BOLD}deployed{RESET}")
        print(f"  {'─' * 36}")
        print(f"  {BOLD}run_cmd{RESET}:     {' '.join(deployed.run_cmd)}")
        if deployed.port is not None:
            print(f"  {BOLD}port{RESET}:        {deployed.port}")
        print(f"  {BOLD}managed{RESET}:     {deployed.managed}")
        if deployed.env:
            print(f"  {BOLD}env{RESET}:")
            for key, val in deployed.env.items():
                print(f"    {key}={val}")
        if deployed.secret_env_keys:
            print(f"  {BOLD}secrets{RESET}:    {', '.join(deployed.secret_env_keys)}")
    else:
        print(f"\n  {DIM}not deployed (run 'castle deploy'){RESET}")

    # Show CLAUDE.md if it exists
    source_dir = None
    if program and program.source_dir:
        source_dir = program.source_dir
    elif spec and spec.program and spec.program in config.programs:
        source_dir = config.programs[spec.program].source_dir

    if source_dir:
        claude_md = _find_claude_md(config.root, source_dir)
        if claude_md:
            print(f"\n{BOLD}{CYAN}CLAUDE.md{RESET}")
            print(f"{CYAN}{'─' * 40}{RESET}")
            print(f"{DIM}{claude_md}{RESET}")

    print()
    return 0


def _info_json(
    config: object,
    name: str,
    program: object | None,
    service: object | None,
    job: object | None,
    deployed: object | None,
) -> int:
    """Output JSON info."""
    data: dict = {"name": name}

    if program:
        data["program"] = program.model_dump(exclude_none=True, exclude={"id"})
    if service:
        data["service"] = service.model_dump(exclude_none=True, exclude={"id"})
    if job:
        data["job"] = job.model_dump(exclude_none=True, exclude={"id"})
    if program:
        data["kinds"] = sorted({k for _, k in config.deployments_of(name)})
    elif service:
        data["kind"] = "service"
    elif job:
        data["kind"] = "job"

    # Resolve stack
    stack = None
    if program and program.stack:
        stack = program.stack
    elif service and service.program and service.program in config.programs:
        stack = config.programs[service.program].stack
    elif job and job.program and job.program in config.programs:
        stack = config.programs[job.program].stack
    if stack:
        data["stack"] = stack

    if deployed:
        data["deployed"] = {
            "manager": deployed.manager,
            "launcher": deployed.launcher,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
            "secret_env_keys": deployed.secret_env_keys,
            "port": deployed.port,
            "managed": deployed.managed,
        }

    print(json.dumps(data, indent=2))
    return 0


def _find_claude_md(root: Path, source_dir: str) -> str | None:
    """Read CLAUDE.md from project directory if it exists."""
    claude_path = root / source_dir / "CLAUDE.md"
    if claude_path.exists():
        return claude_path.read_text()
    return None
