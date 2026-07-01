"""castle program add — adopt an existing repo as a program (no scaffolding).

`castle program create` makes new code from a stack. `castle program add` adopts code that
already exists — a local path, or a git URL to clone. It detects sensible dev
verb commands so a non-castle project becomes usable without writing them by hand.
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from castle_cli.config import REPOS_DIR, load_config, save_config
from castle_cli.manifest import BuildSpec, CommandsSpec, ProgramSpec


def _is_git_url(s: str) -> bool:
    return (
        s.startswith(("http://", "https://", "git@", "ssh://"))
        or s.endswith(".git")
    )


def _detect(src: Path) -> tuple[str | None, dict[str, list[list[str]]]]:
    """Detect (stack, commands) for a source dir.

    Returns a stack name when the project fits a known one (so it inherits those
    defaults), otherwise an explicit commands map. `add` adopts source only; the
    deployment (and thus kind) is declared separately, so no kind is inferred here.
    """
    commands: dict[str, list[list[str]]] = {}

    pyproject = src / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        deps = " ".join(data.get("project", {}).get("dependencies", []))
        stack = "python-fastapi" if ("fastapi" in deps or "uvicorn" in deps) else "python-cli"
        return stack, commands

    if (src / "Cargo.toml").exists():
        commands = {
            "build": [["cargo", "build", "--release"]],
            "test": [["cargo", "test"]],
            "lint": [["cargo", "clippy"]],
            "run": [["cargo", "run"]],
        }
        return None, commands

    if (src / "package.json").exists():
        commands = {
            "build": [["pnpm", "build"]],
            "test": [["pnpm", "test"]],
            "lint": [["pnpm", "lint"]],
        }
        return None, commands

    if (src / "Makefile").exists() or (src / "makefile").exists():
        commands = {"build": [["make"]], "test": [["make", "test"]]}
        return None, commands

    return None, commands


def run_add(args: argparse.Namespace) -> int:
    """Adopt an existing repo as a program."""
    config = load_config()
    target = args.target

    repo_url: str | None = None
    source: str | None = None

    if _is_git_url(target):
        repo_url = target
        name = args.name or Path(target.rstrip("/")).name.removesuffix(".git")
        # Default local clone location; cloned later via `castle clone`.
        source = str(REPOS_DIR / name)
        src_path = Path(source)
    else:
        src_path = Path(target).expanduser().resolve()
        if not src_path.exists():
            print(f"Error: path does not exist: {src_path}")
            return 1
        source = str(src_path)
        name = args.name or src_path.name

    if name in config.programs or name in config.deployments:
        print(f"Error: '{name}' already exists in castle.yaml")
        return 1

    # Detect verbs from the working copy if we have one on disk. `kind` is derived
    # from a deployment, not stored on the program — so `castle add` adopts the
    # source only; declare a deployment separately (castle service/job create).
    stack: str | None = None
    detected_commands: dict[str, list[list[str]]] = {}
    if src_path.exists():
        stack, detected_commands = _detect(src_path)

    prog = ProgramSpec(
        id=name,
        description=args.description or f"Adopted from {target}",
        source=source,
        stack=stack,
        repo=repo_url,
    )
    # `build` is declared via BuildSpec; every other verb via CommandsSpec.
    if detected_commands:
        build_cmds = detected_commands.pop("build", None)
        if build_cmds:
            prog.build = BuildSpec(commands=build_cmds)
        if detected_commands:
            prog.commands = CommandsSpec.model_validate(detected_commands)

    config.programs[name] = prog
    save_config(config)

    print(f"Adopted '{name}' as a program.")
    print(f"  source: {source}")
    if repo_url:
        print(f"  repo:   {repo_url}  (run 'castle clone {name}' to fetch it)")
    if stack:
        print(f"  stack:  {stack}  (verbs inherited from stack defaults)")
    elif detected_commands:
        print(f"  commands detected: {', '.join(sorted(detected_commands))}")
    else:
        print("  no stack/commands detected — declare verbs in castle.yaml as needed")
    return 0
