"""castle tool - manage tools."""

from __future__ import annotations

import argparse

from castle_cli.config import load_config

BOLD = "\033[1m"
RESET = "\033[0m"
DIM = "\033[2m"
CYAN = "\033[96m"


def run_tool(args: argparse.Namespace) -> int:
    """Manage tools."""
    if not args.tool_command:
        print("Usage: castle tool {list|info}")
        return 1

    if args.tool_command == "list":
        return _tool_list()
    elif args.tool_command == "info":
        return _tool_info(args.name)

    return 1


def _tool_list() -> int:
    """List all registered tools."""
    config = load_config()
    tools = {k: v for k, v in config.programs.items() if v.behavior == "tool"}

    if not tools:
        print("No tools registered.")
        return 0

    print(f"\n{BOLD}{CYAN}Tools{RESET}")
    print(f"{CYAN}{'─' * 40}{RESET}")
    for name, manifest in sorted(tools.items()):
        desc = manifest.description or ""
        deps = ""
        if manifest.system_dependencies:
            deps = f"  {DIM}[{', '.join(manifest.system_dependencies)}]{RESET}"
        print(f"  {BOLD}{name:<20}{RESET} {desc}{deps}")

    print()
    return 0


def _tool_info(name: str) -> int:
    """Show detailed info about a tool, including .md documentation."""
    config = load_config()
    if name not in config.programs:
        print(f"Error: '{name}' not found")
        return 1

    manifest = config.programs[name]
    if manifest.behavior != "tool":
        print(f"Error: '{name}' is not a tool")
        return 1

    print(f"\n{BOLD}{name}{RESET}")
    print(f"{'─' * 40}")
    if manifest.description:
        print(f"  {manifest.description}")
    if manifest.version:
        print(f"  {BOLD}version{RESET}:  {manifest.version}")
    if manifest.source:
        print(f"  {BOLD}source{RESET}:   {manifest.source}")
    if manifest.system_dependencies:
        print(f"  {BOLD}requires{RESET}: {', '.join(manifest.system_dependencies)}")

    print()
    return 0
