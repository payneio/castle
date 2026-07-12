"""Tests for the relationship model (core/src/castle_core/relations.py)."""

from __future__ import annotations

import pytest

import castle_core.config as C
from castle_core import relations as R
from castle_core.manifest import (
    CaddyDeployment,
    ProgramSpec,
    Requirement,
    SystemdDeployment,
)
from castle_core.stacks import tools_for


def _dep(program: str, requires: list | None = None) -> SystemdDeployment:
    spec: dict = {
        "manager": "systemd",
        "program": program,
        "run": {"launcher": "command", "argv": [program]},
    }
    if requires is not None:
        spec["requires"] = requires
    return SystemdDeployment.model_validate(spec)


def _static(program: str) -> CaddyDeployment:
    return CaddyDeployment.model_validate(
        {"manager": "caddy", "program": program, "root": "dist"}
    )


def _cfg(programs: dict, deployments: dict) -> C.CastleConfig:
    return C.CastleConfig(
        root=None,
        gateway=C.GatewayConfig(port=9000),
        repo=None,
        programs=programs,
        deployments=deployments,
    )


def test_system_dependencies_is_the_system_requirement_alias() -> None:
    """`system_dependencies` surfaces as a {kind: system} requirement."""
    cfg = _cfg(
        {"t": ProgramSpec(id="t", system_dependencies=["pandoc"])}, {"t": _dep("t")}
    )
    reqs = R.requirements_of(cfg, "t")
    assert [(r.kind, r.ref) for r in reqs] == [("system", "pandoc")]


def test_requirements_merge_system_deps_and_deployment_requires_deduped() -> None:
    """The requirement set unions the program's system_dependencies (as {kind: system})
    with the deployment's own requires, de-duplicated by (kind, ref)."""
    prog = ProgramSpec(id="web", system_dependencies=["pandoc"])
    # Two identical deployment requires — deduped to one.
    dep = _dep("web", requires=[{"ref": "api"}, {"ref": "api"}])
    cfg = _cfg(
        {"web": prog, "api": ProgramSpec(id="api")}, {"web": dep, "api": _dep("api")}
    )
    kinds = {(r.kind, r.ref) for r in R.requirements_of(cfg, "web")}
    assert kinds == {("system", "pandoc"), ("deployment", "api")}  # deduped


def test_deployment_edge_carries_bind_and_counts_fan_in() -> None:
    """A {kind: deployment} requirement becomes an edge (with bind), and the target's
    fan-in is the count of distinct dependents."""
    cfg = _cfg(
        {
            "web": ProgramSpec(id="web"),
            "cli": ProgramSpec(id="cli"),
            "api": ProgramSpec(id="api"),
        },
        {
            "web": _dep("web", requires=[{"ref": "api", "bind": "API_URL"}]),
            "cli": _dep("cli", requires=[{"ref": "api"}]),
            "api": _dep("api"),
        },
    )
    m = R.build_model(cfg, check=False)
    edge = next(e for e in m.edges if e.src == "web" and e.dst == "api")
    assert edge.kind == "deployment" and edge.bind == "API_URL"
    api = next(n for n in m.nodes if n.name == "api")
    assert api.depended_on_by == 2  # web + cli


def test_functional_predicate_reports_unmet(monkeypatch: pytest.MonkeyPatch) -> None:
    """`functional?` is derived: a missing system package is unmet; a present
    deployment requirement is satisfied."""
    prog = ProgramSpec(id="web", system_dependencies=["pandoc"])
    cfg = _cfg(
        {"web": prog, "api": ProgramSpec(id="api")},
        {"web": _dep("web", requires=[{"ref": "api"}]), "api": _dep("api")},
    )
    monkeypatch.setattr(R.shutil, "which", lambda _: None)  # not on PATH
    monkeypatch.setattr(R, "_dpkg_installed", lambda _: False)  # nor as a package
    m = R.build_model(cfg, check=True)
    web = next(n for n in m.nodes if n.name == "web")
    assert web.unmet == ["system:pandoc"]  # deployment:api exists → satisfied
    assert web.functional is False


def test_system_requirement_satisfied_by_package_not_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A package name that isn't a command (poppler-utils) is satisfied when the
    package is installed — a PATH lookup alone would wrongly report it unmet."""
    prog = ProgramSpec(id="t", system_dependencies=["poppler-utils"])
    cfg = _cfg({"t": prog}, {"t": _dep("t")})
    monkeypatch.setattr(R.shutil, "which", lambda _: None)  # no `poppler-utils` binary
    monkeypatch.setattr(R, "_dpkg_installed", lambda pkg: pkg == "poppler-utils")
    t = next(n for n in R.build_model(cfg, check=True).nodes if n.name == "t")
    assert t.functional is True and t.unmet == []


def test_missing_deployment_requirement_is_unmet() -> None:
    cfg = _cfg(
        {"web": ProgramSpec(id="web")},
        {"web": _dep("web", requires=[{"ref": "ghost"}])},
    )
    m = R.build_model(cfg, check=True)
    web = next(n for n in m.nodes if n.name == "web")
    assert web.unmet == ["deployment:ghost"] and web.functional is False


# --- stack toolchains as requirements ----------------------------------------


def test_stack_toolchain_surfaces_as_tool_requirement() -> None:
    """A program's stack contributes its toolchains as {kind: tool} requirements."""
    prog = ProgramSpec(id="svc", stack="python-fastapi")
    cfg = _cfg({"svc": prog}, {"svc": _dep("svc")})
    reqs = {(r.kind, r.ref) for r in R.requirements_of(cfg, "svc")}
    assert ("tool", "uv") in reqs


def test_stack_tool_missing_from_service_path_is_unmet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drift case: uv resolves in the caller's shell PATH but NOT on the
    service's curated runtime PATH → unmet *for the service*, even though a bare
    `which` (what `castle tool list` uses) would report it present."""
    prog = ProgramSpec(id="svc", stack="python-fastapi")
    cfg = _cfg({"svc": prog}, {"svc": _dep("svc")})
    shell_only = "/home/me/.shell-tools"  # a dir the runtime PATH never includes
    monkeypatch.setenv("PATH", shell_only)
    monkeypatch.setattr(
        R.shutil,
        "which",
        lambda cmd, path=None: (
            f"{shell_only}/{cmd}" if path and shell_only in path else None
        ),
    )
    m = R.build_model(cfg, check=True)
    svc = next(n for n in m.nodes if n.name == "svc")
    assert svc.unmet == ["tool:uv"] and svc.functional is False


def test_stack_tool_present_on_service_path_is_satisfied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prog = ProgramSpec(id="svc", stack="python-fastapi")
    cfg = _cfg({"svc": prog}, {"svc": _dep("svc")})
    monkeypatch.setattr(R.shutil, "which", lambda cmd, path=None: f"/usr/bin/{cmd}")
    svc = next(n for n in R.build_model(cfg, check=True).nodes if n.name == "svc")
    assert svc.functional is True and "tool:uv" not in svc.unmet


def test_build_phase_tool_checked_against_build_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A static site's build-only tools (pnpm/node) are checked against the build/dev
    PATH — a static deployment runs no process, so runtime-PATH drift doesn't apply."""
    prog = ProgramSpec(id="ui", stack="react-vite")
    cfg = _cfg({"ui": prog}, {"ui": _static("ui")})
    dev_dir = "/home/me/.local/share/pnpm"
    monkeypatch.setenv("PATH", dev_dir)
    monkeypatch.setattr(
        R.shutil,
        "which",
        lambda cmd, path=None: f"{dev_dir}/{cmd}" if path and dev_dir in path else None,
    )
    ui = next(n for n in R.build_model(cfg, check=True).nodes if n.name == "ui")
    assert ui.functional is True and not [u for u in ui.unmet if u.startswith("tool:")]


def test_hint_for_each_requirement_kind() -> None:
    uv = tools_for("python-fastapi")[0]
    assert "astral.sh" in R.hint_for(Requirement(kind="tool", ref="uv"), uv)
    assert R.hint_for(Requirement(kind="system", ref="pandoc")) == (
        "sudo apt install pandoc"
    )
    assert "api" in R.hint_for(Requirement(kind="deployment", ref="api"))
