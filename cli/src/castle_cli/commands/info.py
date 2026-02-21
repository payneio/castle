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


def run_info(args: argparse.Namespace) -> int:
    """Show detailed info for a component."""
    config = load_config()
    name = args.project

    if name not in config.components:
        print(f"Error: component '{name}' not found in castle.yaml")
        return 1

    manifest = config.components[name]

    if getattr(args, "json", False):
        data = manifest.model_dump(exclude_none=True)
        # Include CLAUDE.md content if it exists
        cwd = manifest.run.cwd if manifest.run else None
        claude_md = _find_claude_md(config.root, cwd or name)
        if claude_md:
            data["claude_md"] = claude_md
        print(json.dumps(data, indent=2))
        return 0

    # Human-readable output
    print(f"\n{BOLD}{name}{RESET}")
    print(f"{'─' * 40}")
    print(f"  {BOLD}roles{RESET}:       {', '.join(r.value for r in manifest.roles)}")
    if manifest.description:
        print(f"  {BOLD}description{RESET}: {manifest.description}")

    # Run spec
    if manifest.run:
        print(f"  {BOLD}runner{RESET}:      {manifest.run.runner}")
        if manifest.run.cwd:
            print(f"  {BOLD}cwd{RESET}:         {manifest.run.cwd}")
        if hasattr(manifest.run, "tool"):
            print(f"  {BOLD}tool{RESET}:        {manifest.run.tool}")
        elif hasattr(manifest.run, "argv"):
            print(f"  {BOLD}argv{RESET}:        {manifest.run.argv}")
        elif hasattr(manifest.run, "image"):
            print(f"  {BOLD}image{RESET}:       {manifest.run.image}")
        if manifest.run.env:
            print(f"  {BOLD}env{RESET}:")
            for key, val in manifest.run.env.items():
                print(f"    {key}: {val}")

    # Expose
    if manifest.expose and manifest.expose.http:
        http = manifest.expose.http
        print(f"  {BOLD}port{RESET}:        {http.internal.port}")
        if http.health_path:
            print(f"  {BOLD}health{RESET}:      {http.health_path}")

    # Proxy
    if manifest.proxy and manifest.proxy.caddy:
        caddy = manifest.proxy.caddy
        if caddy.path_prefix:
            print(f"  {BOLD}path{RESET}:        {caddy.path_prefix}")

    # Manage
    if manifest.manage and manifest.manage.systemd:
        sd = manifest.manage.systemd
        print(f"  {BOLD}systemd{RESET}:     enabled={sd.enable}, restart={sd.restart.value}")

    # Install
    if manifest.install and manifest.install.path:
        pi = manifest.install.path
        print(f"  {BOLD}install{RESET}:     path" + (f" (alias: {pi.alias})" if pi.alias else ""))

    # Tags
    if manifest.tags:
        print(f"  {BOLD}tags{RESET}:        {', '.join(manifest.tags)}")

    # Capabilities
    if manifest.provides:
        print(f"  {BOLD}provides{RESET}:")
        for cap in manifest.provides:
            print(f"    - {cap.type}" + (f" ({cap.name})" if cap.name else ""))
    if manifest.consumes:
        print(f"  {BOLD}consumes{RESET}:")
        for cap in manifest.consumes:
            print(f"    - {cap.type}" + (f" ({cap.name})" if cap.name else ""))

    # Show CLAUDE.md if it exists
    cwd = manifest.run.cwd if manifest.run else None
    claude_md = _find_claude_md(config.root, cwd or name)
    if claude_md:
        print(f"\n{BOLD}{CYAN}CLAUDE.md{RESET}")
        print(f"{CYAN}{'─' * 40}{RESET}")
        print(f"{DIM}{claude_md}{RESET}")

    print()
    return 0


def _find_claude_md(root: Path, working_dir: str) -> str | None:
    """Read CLAUDE.md from project directory if it exists."""
    claude_path = root / working_dir / "CLAUDE.md"
    if claude_path.exists():
        return claude_path.read_text()
    return None
