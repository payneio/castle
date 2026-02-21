"""castle tool - manage tools."""

from __future__ import annotations

import argparse
from pathlib import Path

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
    """List tools grouped by category."""
    config = load_config()
    tools = {k: v for k, v in config.components.items() if v.tool}

    if not tools:
        print("No tools registered.")
        return 0

    by_category: dict[str, list[tuple[str, object]]] = {}
    for name, manifest in tools.items():
        cat = manifest.tool.category or "uncategorized"
        by_category.setdefault(cat, []).append((name, manifest))

    for category in sorted(by_category):
        items = by_category[category]
        print(f"\n{BOLD}{CYAN}{category}{RESET}")
        print(f"{CYAN}{'─' * 40}{RESET}")
        for name, manifest in sorted(items):
            desc = manifest.description or ""
            deps = ""
            if manifest.tool.system_dependencies:
                deps = f"  {DIM}[{', '.join(manifest.tool.system_dependencies)}]{RESET}"
            print(f"  {BOLD}{name:<20}{RESET} {desc}{deps}")

    print()
    return 0


def _tool_info(name: str) -> int:
    """Show detailed info about a tool, including .md documentation."""
    config = load_config()
    if name not in config.components:
        print(f"Error: '{name}' not found")
        return 1

    manifest = config.components[name]
    if not manifest.tool:
        print(f"Error: '{name}' is not a tool")
        return 1

    t = manifest.tool

    print(f"\n{BOLD}{name}{RESET}")
    print(f"{'─' * 40}")
    if manifest.description:
        print(f"  {manifest.description}")
    print(f"  {BOLD}category{RESET}: {t.category or 'uncategorized'}")
    print(f"  {BOLD}version{RESET}:  {t.version}")
    if t.source:
        print(f"  {BOLD}source{RESET}:   {t.source}")
    if t.system_dependencies:
        print(f"  {BOLD}requires{RESET}: {', '.join(t.system_dependencies)}")

    # Read and display .md documentation if available
    if t.source:
        md_path = _find_md_for_tool(config.root, t.source, name, t.category)
        if md_path and md_path.exists():
            content = md_path.read_text()
            # Strip YAML frontmatter
            if content.startswith("---\n"):
                end = content.find("\n---\n", 4)
                if end != -1:
                    content = content[end + 5:]
            content = content.strip()
            if content:
                print(f"\n{BOLD}{CYAN}Documentation{RESET}")
                print(f"{CYAN}{'─' * 40}{RESET}")
                print(f"{DIM}{content}{RESET}")

    print()
    return 0


def _find_md_for_tool(
    root: Path, source: str, tool_name: str, category: str | None = None,
) -> Path | None:
    """Find the .md documentation file for a tool source path."""
    source_path = root / source
    if source_path.is_file():
        md = source_path.with_suffix(".md")
        if md.exists():
            return md
    elif source_path.is_dir():
        # Directory source — look for src/<category>/<tool_name>.md
        py_name = tool_name.replace("-", "_")
        if category:
            md = source_path / "src" / category / f"{py_name}.md"
            if md.exists():
                return md
    return None
