"""castle stack — the stacks lens (toolchains a program's stack needs).

A *stack* (python-fastapi, react-vite, hugo, …) is creation-time guidance that
also carries the **host toolchains** its programs need to build and run (`uv`,
`pnpm`, `hugo`, …). This lens makes those dependencies visible and tells you
whether they're present *where the running service needs them* — the drift a bare
`which` in your shell misses — with a copyable fix when one is absent.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from castle_cli.config import load_config

if TYPE_CHECKING:
    from castle_core.stack_status import StackStatus

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
GREEN = "\033[92m"
RED = "\033[91m"
GREY = "\033[90m"
CYAN = "\033[96m"


def _record(st: StackStatus) -> dict:
    d = asdict(st)
    d["in_use"] = st.in_use
    d["ok"] = st.ok
    return d


def run_stack_list(args: argparse.Namespace) -> int:
    """List stacks with their toolchain health, program count, and dev verbs."""
    from castle_core.stack_status import all_stack_status

    config = load_config()
    # Skip per-tool version probes for the list (a subprocess per tool) — keep it snappy.
    stacks = all_stack_status(config, with_version=False)

    if getattr(args, "json", False):
        print(json.dumps([_record(s) for s in stacks], indent=2))
        return 0

    print(f"\n{BOLD}Stacks{RESET}")
    print("─" * 64)
    width = max((len(s.name) for s in stacks), default=0)
    for s in stacks:
        if not s.tools:
            dot = f"{GREY}○{RESET}"
        else:
            dot = f"{GREEN}●{RESET}" if s.ok else f"{RED}●{RESET}"
        missing = [t.command for t in s.tools if not t.present]
        tools = ", ".join(
            (f"{RED}{t.command}{RESET}" if not t.present else t.command) for t in s.tools
        )
        used = (
            f"{len(s.programs)} program{'s' if len(s.programs) != 1 else ''}"
            if s.in_use
            else f"{GREY}unused{RESET}"
        )
        tail = f"  {DIM}{used}{RESET}"
        tools_str = f"  {DIM}tools:{RESET} {tools}" if tools else ""
        print(f"  {dot} {BOLD}{s.name:<{width}}{RESET}{tools_str}{tail}")
        if missing:
            print(f"      {RED}missing:{RESET} {', '.join(missing)}")
    print()
    return 0


def run_stack_info(args: argparse.Namespace) -> int:
    """Show one stack: each tool's presence + version + fix, and who uses it."""
    from castle_core.stack_status import stack_status

    config = load_config()
    name = args.name
    st = stack_status(config, name)
    if st is None:
        from castle_core.stacks import available_stacks

        print(f"Error: no stack '{name}'. Known: {', '.join(available_stacks())}")
        return 1

    if getattr(args, "json", False):
        print(json.dumps(_record(st), indent=2))
        return 0

    print(f"\n{BOLD}{st.name}{RESET}")
    print("─" * 48)
    if st.verbs:
        print(f"  {BOLD}verbs{RESET}:    {', '.join(st.verbs)}")
    print(f"  {BOLD}used by{RESET}:  ", end="")
    print(", ".join(st.programs) if st.programs else f"{GREY}nothing{RESET}")

    print(f"\n  {BOLD}toolchain{RESET}")
    if not st.tools:
        print(f"    {GREY}no host tools required{RESET}")
    for t in st.tools:
        mark = f"{GREEN}✓{RESET}" if t.present else f"{RED}✗{RESET}"
        ver = f"  {DIM}{t.version}{RESET}" if t.version else ""
        print(f"    {mark} {BOLD}{t.command}{RESET}  {DIM}{t.purpose} ({t.phase}){RESET}{ver}")
        if not t.present:
            print(f"        {CYAN}{t.install_hint}{RESET}")
    print()
    return 0
