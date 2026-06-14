"""Stack protocol — lifecycle actions for each development stack."""

from __future__ import annotations

import asyncio
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from castle_core.manifest import ProgramSpec

DEV_ACTIONS = ["build", "test", "lint", "type-check", "check", "run"]
INSTALL_ACTIONS = ["install", "uninstall"]
ALL_ACTIONS = DEV_ACTIONS + INSTALL_ACTIONS

# Verbs a stack handler can provide (everything except `run`, which is declared-only).
_STACK_VERBS = {"build", "test", "lint", "type-check", "check", "install", "uninstall"}
# Verbs whose handler method name differs from the verb spelling.
_VERB_METHOD = {"type-check": "type_check"}

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
        pkg_spec = str(src)
        if comp.install_extras:
            pkg_spec += "[" + ",".join(comp.install_extras) + "]"
        rc, output = await _run(
            ["uv", "tool", "install", "--editable", pkg_spec, "--force"], src
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
        """Build the static assets in place. The gateway serves them directly from
        <source>/<build.outputs[0]> — no copy into a central content dir."""
        result = await self.build(name, comp, root)
        if result.status != "ok":
            return ActionResult(
                component=name, action="install", status="error",
                output=f"Build failed:\n{result.output}",
            )
        outputs = comp.build.outputs if comp.build else []
        if not outputs:
            return ActionResult(
                component=name, action="install", status="error",
                output="No build outputs configured.",
            )
        dist = _source_dir(comp, root) / outputs[0]
        return ActionResult(
            component=name, action="install", status="ok",
            output=f"Built; served in place from {dist}",
        )

    async def uninstall(self, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
        """Static frontends have no install footprint to remove (served in place).

        Deactivating one means dropping its gateway route — handled by removing the
        program from the registry, not by deleting build output."""
        return ActionResult(
            component=name, action="uninstall", status="ok",
            output=f"{name}: served in place; nothing to uninstall.",
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


def _declared_commands(comp: ProgramSpec, verb: str) -> list[list[str]] | None:
    """Declared argv-lists for a verb, or None.

    `build` is declared via BuildSpec.commands; every other verb via CommandsSpec.
    """
    if verb == "build":
        if comp.build and comp.build.commands:
            return comp.build.commands
        return None
    if comp.commands is not None:
        return comp.commands.for_verb(verb)
    return None


def _stack_provides(comp: ProgramSpec, verb: str) -> bool:
    """Whether the program's stack handler can run this verb."""
    return bool(comp.source) and verb in _STACK_VERBS and get_handler(comp.stack) is not None


def is_available(comp: ProgramSpec, verb: str) -> bool:
    """Whether a verb can be run for a program (declared command or stack default)."""
    if _declared_commands(comp, verb) is not None:
        return True
    if verb == "check":
        return any(is_available(comp, sub) for sub in ("lint", "type-check", "test"))
    return _stack_provides(comp, verb)


def available_actions(comp: ProgramSpec) -> list[str]:
    """Return the list of verbs available for a program (resolution-aware)."""
    if not comp.source:
        return []
    return [verb for verb in ALL_ACTIONS if is_available(comp, verb)]


async def _run_declared(
    name: str, verb: str, cmds: list[list[str]], src: Path
) -> ActionResult:
    """Run declared argv-lists in sequence; stop at the first failure."""
    outputs: list[str] = []
    for argv in cmds:
        rc, output = await _run(argv, src)
        outputs.append(output)
        if rc != 0:
            return ActionResult(component=name, action=verb, status="error", output="".join(outputs))
    return ActionResult(component=name, action=verb, status="ok", output="".join(outputs))


async def run_action(verb: str, name: str, comp: ProgramSpec, root: Path) -> ActionResult:
    """Resolve and run a verb: declared command → stack default → unavailable.

    This is the single entry point callers should use; it replaces reaching for
    get_handler(...).<method>(...) directly so the override logic stays in one place.
    """
    # `check` is a composite that must respect per-verb overrides — unless the
    # program declares its own `check`, run each available sub-verb via run_action.
    if verb == "check" and _declared_commands(comp, "check") is None:
        subs = [s for s in ("lint", "type-check", "test") if is_available(comp, s)]
        if not subs:
            return ActionResult(
                component=name, action="check", status="error",
                output="No checkable verbs available.",
            )
        for sub in subs:
            result = await run_action(sub, name, comp, root)
            if result.status != "ok":
                return ActionResult(
                    component=name, action="check", status="error",
                    output=f"{sub} failed:\n{result.output}",
                )
        return ActionResult(component=name, action="check", status="ok")

    # 1. Declared command overrides the stack default.
    declared = _declared_commands(comp, verb)
    if declared is not None:
        try:
            src = _source_dir(comp, root)
        except ValueError:
            return ActionResult(component=name, action=verb, status="error", output="No source directory")
        return await _run_declared(name, verb, declared, src)

    # 2. Stack default.
    handler = get_handler(comp.stack)
    if handler is not None and verb in _STACK_VERBS:
        method = getattr(handler, _VERB_METHOD.get(verb, verb), None)
        if method is not None:
            return await method(name, comp, root)

    # 3. Unavailable.
    return ActionResult(
        component=name, action=verb, status="error",
        output=f"Verb '{verb}' is not available for '{name}' "
        f"(no declared command and no stack handler provides it).",
    )
