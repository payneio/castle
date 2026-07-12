"""Stack dependency status — the derived, per-stack health the `castle stack`
command, the ``GET /stacks`` API, and the dashboard Stacks page all render.

A *stack* declares the host toolchains it needs (``stacks.ToolRequirement``); this
module answers, for each stack: which programs/deployments use it, whether its
tools are present *where the using deployments need them* (run-phase tools against
a service's runtime PATH — the drift the plain ``which`` a shell does misses), and
the copyable fix when one is missing. It's the single source of truth so the CLI,
API, and UI never disagree.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

from castle_core.config import CastleConfig
from castle_core.generators.systemd import runtime_path
from castle_core.relations import _build_path, _tool_available
from castle_core.stacks import ToolRequirement, available_stacks, get_handler, tools_for


@dataclass
class ToolStatus:
    command: str
    purpose: str
    phase: str  # run | build | both
    present: bool  # resolvable where the using deployments need it
    install_hint: str  # copyable fix (shown when absent)
    version: str | None = None  # best-effort `--version`, when present


@dataclass
class StackStatus:
    name: str
    tools: list[ToolStatus] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)  # programs on this stack
    deployments: list[str] = field(default_factory=list)  # their deployments
    verbs: list[str] = field(default_factory=list)  # dev verbs the stack provides
    has_enabled_deployment: bool = False  # ≥1 enabled deployment uses it

    @property
    def in_use(self) -> bool:
        return bool(self.programs)

    @property
    def ok(self) -> bool:
        """All needed tools present (vacuously true for a stack with no tools)."""
        return all(t.present for t in self.tools)


def _version(command: str, path: str) -> str | None:
    """Best-effort tool version — the first `<cmd> --version` line (falls back to
    `<cmd> version` for tools like hugo). Never raises; returns None on any trouble."""
    exe = shutil.which(command, path=path)
    if not exe:
        return None
    for argv in ([exe, "--version"], [exe, "version"]):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        out = (r.stdout or r.stderr or "").strip()
        if r.returncode == 0 and out:
            return out.splitlines()[0].strip()
    return None


def _tool_status(
    tool: ToolRequirement,
    using_deps: list[object],
    *,
    with_version: bool,
) -> ToolStatus:
    # Present where it's needed: a run/both tool must resolve for EVERY using
    # deployment (a service's runtime PATH); with no deployments, check generically.
    if using_deps:
        present = all(_tool_available(dep, tool) for dep in using_deps)
    elif tool.phase in ("run", "both"):
        present = shutil.which(tool.command, path=runtime_path()) is not None
    else:
        present = shutil.which(tool.command, path=_build_path()) is not None
    # A version is only meaningful when the tool is present; probe the path that
    # matched (runtime for run/both, build otherwise) so it reflects what's used.
    probe_path = runtime_path() if tool.phase in ("run", "both") else _build_path()
    version = _version(tool.command, probe_path) if (present and with_version) else None
    return ToolStatus(
        command=tool.command,
        purpose=tool.purpose,
        phase=tool.phase,
        present=present,
        install_hint=tool.install_hint,
        version=version,
    )


def stack_status(
    config: CastleConfig, name: str, *, with_version: bool = True
) -> StackStatus | None:
    """The dependency status of one stack, or None if castle has no such handler."""
    handler = get_handler(name)
    if handler is None:
        return None
    programs = sorted(p for p, c in config.programs.items() if c.stack == name)
    deps: list[tuple[str, object]] = []  # (deployment-name, spec)
    enabled = False
    for _kind, dep_name, dep in config.all_deployments():
        prog = config.programs.get(dep.program or dep_name)
        if prog and prog.stack == name:
            deps.append((dep_name, dep))
            enabled = enabled or getattr(dep, "enabled", True)
    dep_specs = [d for _n, d in deps]
    return StackStatus(
        name=name,
        tools=[
            _tool_status(t, dep_specs, with_version=with_version)
            for t in tools_for(name)
        ],
        programs=programs,
        deployments=sorted(n for n, _d in deps),
        verbs=sorted(handler.provides),
        has_enabled_deployment=enabled,
    )


def all_stack_status(
    config: CastleConfig, *, with_version: bool = True
) -> list[StackStatus]:
    """Dependency status for every stack castle knows — the Stacks catalog."""
    out = []
    for name in available_stacks():
        st = stack_status(config, name, with_version=with_version)
        if st is not None:
            out.append(st)
    return out
