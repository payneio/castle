"""castle info - show detailed component information."""

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


def _load_deployed_component(name: str) -> object | None:
    """Try to load a specific deployed component from registry."""
    try:
        from castle_core.registry import load_registry

        registry = load_registry()
        return registry.deployed.get(name)
    except (FileNotFoundError, ValueError):
        return None


def run_info(args: argparse.Namespace) -> int:
    """Show detailed info for a component, service, or job."""
    config = load_config()
    name = args.project

    # Look up in all sections
    component = config.components.get(name)
    service = config.services.get(name)
    job = config.jobs.get(name)

    if not component and not service and not job:
        print(f"Error: '{name}' not found in castle.yaml")
        return 1

    deployed = _load_deployed_component(name)

    if getattr(args, "json", False):
        return _info_json(config, name, component, service, job, deployed)

    # Human-readable output
    print(f"\n{BOLD}{name}{RESET}")
    print(f"{'─' * 40}")

    # Determine category
    if service:
        print(f"  {BOLD}category{RESET}:    service")
    elif job:
        print(f"  {BOLD}category{RESET}:    job")
    elif component:
        if component.tool or (component.install and component.install.path):
            print(f"  {BOLD}category{RESET}:    tool")
        elif component.build:
            print(f"  {BOLD}category{RESET}:    frontend")
        else:
            print(f"  {BOLD}category{RESET}:    component")

    # Component info
    if component:
        if component.description:
            print(f"  {BOLD}description{RESET}: {component.description}")
        if component.source:
            print(f"  {BOLD}source{RESET}:      {component.source}")
        if component.install and component.install.path:
            pi = component.install.path
            print(f"  {BOLD}install{RESET}:     path" + (f" (alias: {pi.alias})" if pi.alias else ""))
        if component.tool:
            t = component.tool
            if t.system_dependencies:
                print(f"  {BOLD}requires{RESET}:    {', '.join(t.system_dependencies)}")
        if component.tags:
            print(f"  {BOLD}tags{RESET}:        {', '.join(component.tags)}")

    # Service info
    spec = service or job
    if spec:
        desc = spec.description
        if not desc and spec.component and spec.component in config.components:
            desc = config.components[spec.component].description
        if desc and not (component and component.description == desc):
            print(f"  {BOLD}description{RESET}: {desc}")
        if spec.component:
            print(f"  {BOLD}component{RESET}:   {spec.component}")

        # Run spec
        print(f"  {BOLD}runner{RESET}:      {spec.run.runner}")
        if hasattr(spec.run, "tool"):
            print(f"  {BOLD}tool{RESET}:        {spec.run.tool}")
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
        if service.proxy and service.proxy.caddy:
            caddy = service.proxy.caddy
            if caddy.path_prefix:
                print(f"  {BOLD}path{RESET}:        {caddy.path_prefix}")
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
    else:
        print(f"\n  {DIM}not deployed (run 'castle deploy'){RESET}")

    # Show CLAUDE.md if it exists
    source_dir = None
    if component and component.source_dir:
        source_dir = component.source_dir
    elif spec and spec.component and spec.component in config.components:
        source_dir = config.components[spec.component].source_dir

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
    component: object | None,
    service: object | None,
    job: object | None,
    deployed: object | None,
) -> int:
    """Output JSON info."""
    data: dict = {"name": name}

    if component:
        data["component"] = component.model_dump(exclude_none=True, exclude={"id"})
    if service:
        data["service"] = service.model_dump(exclude_none=True, exclude={"id"})
        data["category"] = "service"
    if job:
        data["job"] = job.model_dump(exclude_none=True, exclude={"id"})
        data["category"] = "job"
    if not service and not job and component:
        if component.tool or (component.install and component.install.path):
            data["category"] = "tool"
        elif component.build:
            data["category"] = "frontend"
        else:
            data["category"] = "component"

    if deployed:
        data["deployed"] = {
            "runner": deployed.runner,
            "run_cmd": deployed.run_cmd,
            "env": deployed.env,
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
