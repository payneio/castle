"""castle program add — adopt an existing repo as a program (no scaffolding).

`castle program create` makes new code from a stack. `castle program add` adopts code that
already exists — a local path, or a git URL to clone. It detects sensible dev
verb commands so a non-castle project becomes usable without writing them by hand.

The adopt logic itself lives in ``castle_core.adopt`` so the CLI and the API
(`POST /programs/adopt`, the dashboard's "Add program") behave identically.
"""

from __future__ import annotations

import argparse

from castle_core.adopt import AdoptError, build_adopted_program

from castle_cli.config import load_config, save_config


def run_add(args: argparse.Namespace) -> int:
    """Adopt an existing repo as a program."""
    config = load_config()

    try:
        adopted = build_adopted_program(
            config, args.target, name=args.name, description=args.description
        )
    except AdoptError as e:
        print(f"Error: {e}")
        return 1

    config.programs[adopted.name] = adopted.spec
    save_config(config)

    print(f"Adopted '{adopted.name}' as a program.")
    print(f"  source: {adopted.source}")
    if adopted.repo:
        print(f"  repo:   {adopted.repo}  (run 'castle clone {adopted.name}' to fetch it)")
    if adopted.stack:
        print(f"  stack:  {adopted.stack}  (verbs inherited from stack defaults)")
    elif adopted.commands:
        print(f"  commands detected: {', '.join(adopted.commands)}")
    else:
        print("  no stack/commands detected — declare verbs in castle.yaml as needed")
    return 0
