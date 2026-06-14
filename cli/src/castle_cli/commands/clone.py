"""castle clone — clone source for programs that declare a `repo:` URL.

Used to provision a fresh machine: every program with a `repo:` and a missing
local `source:` gets cloned. A program whose source already exists is skipped.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from castle_cli.config import REPOS_DIR, load_config


def _clone_one(name: str, repo: str, source: str | None, ref: str | None) -> bool:
    dest = Path(source) if source else REPOS_DIR / name
    if dest.exists():
        print(f"  {name}: already present at {dest}, skipping")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", repo, str(dest)]
    print(f"  {name}: cloning {repo} → {dest}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  {name}: clone failed:\n{result.stderr}")
        return False
    if ref:
        co = subprocess.run(
            ["git", "-C", str(dest), "checkout", ref], capture_output=True, text=True
        )
        if co.returncode != 0:
            print(f"  {name}: checkout {ref} failed:\n{co.stderr}")
            return False
    return True


def run_clone(args: argparse.Namespace) -> int:
    config = load_config()

    if getattr(args, "name", None):
        if args.name not in config.programs:
            print(f"Unknown program: {args.name}")
            return 1
        prog = config.programs[args.name]
        if not prog.repo:
            print(f"{args.name} has no repo: URL to clone from")
            return 1
        return 0 if _clone_one(args.name, prog.repo, prog.source, prog.ref) else 1

    # Clone all programs that declare a repo: and lack a present source.
    all_ok = True
    cloned_any = False
    for name, prog in config.programs.items():
        if not prog.repo:
            continue
        cloned_any = True
        if not _clone_one(name, prog.repo, prog.source, prog.ref):
            all_ok = False
    if not cloned_any:
        print("No programs declare a repo: URL.")
    return 0 if all_ok else 1
