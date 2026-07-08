"""Adopt an existing repo as a program — shared by the CLI (`castle program add`)
and the API (`POST /programs/adopt`).

`create` scaffolds new code from a stack; `add` adopts code that already exists —
a local path, or a git URL to clone later. Keeping the target parsing, stack /
command sniffing, and ProgramSpec build here means both front-ends behave
identically (the logic used to live only in the CLI).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from castle_core.config import CastleConfig
from castle_core.manifest import BuildSpec, CommandsSpec, ProgramSpec


class AdoptError(ValueError):
    """A program can't be adopted (bad path, or the name already exists)."""


def is_git_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@", "ssh://")) or s.endswith(".git")


def looks_like_program(src: Path) -> bool:
    """Whether a directory holds something castle can adopt (a project manifest or
    a git repo). Used to flag candidates in the filesystem browser."""
    return (
        (src / ".git").exists()
        or (src / "pyproject.toml").exists()
        or (src / "Cargo.toml").exists()
        or (src / "package.json").exists()
        or (src / "Makefile").exists()
        or (src / "makefile").exists()
    )


def detect_stack_commands(src: Path) -> tuple[str | None, dict[str, list[list[str]]]]:
    """Detect (stack, commands) for a source dir.

    Returns a stack name when the project fits a known one (so it inherits those
    defaults), otherwise an explicit commands map. Adoption takes source only; the
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


@dataclass
class Adopted:
    """The result of building a program spec from an adopt target — the caller
    persists it (``config.programs[name] = spec``; then save/write)."""

    name: str
    spec: ProgramSpec
    source: str
    stack: str | None = None
    repo: str | None = None
    commands: list[str] = field(default_factory=list)


def build_adopted_program(
    config: CastleConfig,
    target: str,
    name: str | None = None,
    description: str = "",
) -> Adopted:
    """Build (but do not save) a ProgramSpec adopting ``target``.

    ``target`` is a local path or a git URL. Raises :class:`AdoptError` if a local
    path doesn't exist or the resolved name already exists in the config. Does not
    mutate ``config`` — the caller assigns ``config.programs[name]`` and persists.
    """
    repo_url: str | None = None

    if is_git_url(target):
        repo_url = target
        name = name or Path(target.rstrip("/")).name.removesuffix(".git")
        # Default local clone location; cloned later via `castle clone`.
        source = str(config.repos_dir / name)
        src_path = Path(source)
    else:
        src_path = Path(target).expanduser().resolve()
        if not src_path.exists():
            raise AdoptError(f"path does not exist: {src_path}")
        source = str(src_path)
        name = name or src_path.name

    if name in config.programs or config.deployments_named(name):
        raise AdoptError(f"'{name}' already exists in castle.yaml")

    # Detect verbs from the working copy if we have one on disk. `kind` is derived
    # from a deployment, not stored on the program — so adoption takes source only;
    # declare a deployment separately (castle service/job create).
    stack: str | None = None
    detected: dict[str, list[list[str]]] = {}
    if src_path.exists():
        stack, detected = detect_stack_commands(src_path)

    spec = ProgramSpec(
        id=name,
        description=description or f"Adopted from {target}",
        source=source,
        stack=stack,
        repo=repo_url,
    )
    # `build` is declared via BuildSpec; every other verb via CommandsSpec.
    if detected:
        build_cmds = detected.pop("build", None)
        if build_cmds:
            spec.build = BuildSpec(commands=build_cmds)
        if detected:
            spec.commands = CommandsSpec.model_validate(detected)

    return Adopted(
        name=name,
        spec=spec,
        source=source,
        stack=stack,
        repo=repo_url,
        commands=sorted(detected),
    )
