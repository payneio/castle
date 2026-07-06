"""Tests for the relationship model (core/src/castle_core/relations.py)."""

from __future__ import annotations

import pytest

import castle_core.config as C
from castle_core import relations as R
from castle_core.manifest import ProgramSpec, SystemdDeployment


def _dep(program: str, requires: list | None = None) -> SystemdDeployment:
    spec: dict = {
        "manager": "systemd",
        "program": program,
        "run": {"launcher": "command", "argv": [program]},
    }
    if requires is not None:
        spec["requires"] = requires
    return SystemdDeployment.model_validate(spec)


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
        {"web": ProgramSpec(id="web"), "cli": ProgramSpec(id="cli"), "api": ProgramSpec(id="api")},
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
