"""Stack protocol — lifecycle actions for each development stack."""

from __future__ import annotations

import asyncio
import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from castle_core.config import STATIC_DIR
from castle_core.manifest import ProgramSpec

DEV_ACTIONS = ["build", "test", "lint", "type-check", "check"]
INSTALL_ACTIONS = ["install", "uninstall"]
ALL_ACTIONS = DEV_ACTIONS + INSTALL_ACTIONS

# User-local tool directories that may not be on the systemd service PATH.
_EXTRA_PATH_DIRS = [
    Path.home() / ".local" / "share" / "pnpm",
    Path.home() / ".local" / "bin",
]


@dataclass
class ActionResult:
    """Result of a stack lifecycle action."""

    component: str
    action: str
    status: str  # "ok" | "error"
    output: str = ""


def _build_env() -> dict[str, str]:
    """Build a subprocess env with user tool dirs on PATH."""
    env = os.environ.copy()
    extra = ":".join(str(d) for d in _EXTRA_PATH_DIRS if d.exists())
    if extra:
        env["PATH"] = extra + ":" + env.get("PATH", "")
    return env


async def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run a subprocess and return (returncode, combined output)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=_build_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, (stdout or b"").decode()


def _source_dir(comp: ProgramSpec, root: Path) -> Path:
    """Resolve source directory, raising ValueError if absent."""
    if not comp.source:
        raise ValueError("No source directory")
    return root / comp.source


class StackHandler:
    """Base class — subclasses implement each lifecycle action."""

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def type_check(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def check(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Composite: lint + type-check + test. Runs all, reports first failure."""
        for action_fn, action_name in [
            (self.lint, "lint"),
            (self.type_check, "type-check"),
            (self.test, "test"),
        ]:
            result = await action_fn(name, comp, root)
            if result.status != "ok":
                return ActionResult(
                    component=name,
                    action="check",
                    status="error",
                    output=f"{action_name} failed:\n{result.output}",
                )
        return ActionResult(component=name, action="check", status="ok")

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        raise NotImplementedError


class PythonHandler(StackHandler):
    """Handler for python-cli and python-fastapi stacks."""

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "sync"], src)
        return ActionResult(
            component=name, action="build", status="ok" if rc == 0 else "error", output=output
        )

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        if not (src / "tests").exists():
            return ActionResult(
                component=name, action="test", status="ok",
                output="No tests directory found, skipping.",
            )
        rc, output = await _run(["uv", "run", "pytest", "tests/", "-v"], src)
        return ActionResult(
            component=name, action="test", status="ok" if rc == 0 else "error", output=output
        )

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "run", "ruff", "check", "."], src)
        return ActionResult(
            component=name, action="lint", status="ok" if rc == 0 else "error", output=output
        )

    async def type_check(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["uv", "run", "pyright"], src)
        return ActionResult(
            component=name, action="type-check", status="ok" if rc == 0 else "error", output=output
        )

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(
            ["uv", "tool", "install", "--editable", str(src), "--force"], src
        )
        return ActionResult(
            component=name, action="install", status="ok" if rc == 0 else "error", output=output
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        pkg_name = src.name
        pyproject = src / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            pkg_name = data.get("project", {}).get("name", pkg_name)
        rc, output = await _run(["uv", "tool", "uninstall", pkg_name], src)
        return ActionResult(
            component=name, action="uninstall", status="ok" if rc == 0 else "error", output=output
        )


class ReactViteHandler(StackHandler):
    """Handler for react-vite stack."""

    async def build(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["pnpm", "build"], src)
        return ActionResult(
            component=name, action="build", status="ok" if rc == 0 else "error", output=output
        )

    async def test(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["pnpm", "test"], src)
        return ActionResult(
            component=name, action="test", status="ok" if rc == 0 else "error", output=output
        )

    async def lint(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["pnpm", "lint"], src)
        return ActionResult(
            component=name, action="lint", status="ok" if rc == 0 else "error", output=output
        )

    async def type_check(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        src = _source_dir(comp, root)
        rc, output = await _run(["pnpm", "type-check"], src)
        return ActionResult(
            component=name, action="type-check", status="ok" if rc == 0 else "error", output=output
        )

    async def install(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Build and copy static assets to ~/.castle/static/{name}/."""
        result = await self.build(name, comp, root)
        if result.status != "ok":
            return ActionResult(
                component=name, action="install", status="error",
                output=f"Build failed:\n{result.output}",
            )

        src = _source_dir(comp, root)
        outputs = comp.build.outputs if comp.build else []
        if not outputs:
            return ActionResult(
                component=name, action="install", status="error",
                output="No build outputs configured.",
            )

        for output_dir in outputs:
            src_path = src / output_dir
            if src_path.exists():
                dest = STATIC_DIR / name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src_path, dest)

        return ActionResult(
            component=name, action="install", status="ok",
            output=f"Built and deployed to {STATIC_DIR / name}",
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Remove static assets from ~/.castle/static/{name}/."""
        dest = STATIC_DIR / name
        if dest.exists():
            shutil.rmtree(dest)
            return ActionResult(
                component=name, action="uninstall", status="ok",
                output=f"Removed {dest}",
            )
        return ActionResult(
            component=name, action="uninstall", status="ok",
            output=f"Nothing to remove ({dest} does not exist)",
        )


HANDLERS: dict[str, StackHandler] = {
    "python-cli": PythonHandler(),
    "python-fastapi": PythonHandler(),
    "react-vite": ReactViteHandler(),
}


def get_handler(stack: str | None) -> StackHandler | None:
    """Get the handler for a given stack, or None if unsupported."""
    if stack is None:
        return None
    return HANDLERS.get(stack)


def available_actions(comp: ProgramSpec) -> list[str]:
    """Return the list of actions available for a program."""
    if not comp.source:
        return []
    handler = get_handler(comp.stack)
    if handler is None:
        return []
    return list(ALL_ACTIONS)
