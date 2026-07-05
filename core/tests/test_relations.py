"""Tests for the relationship model (core/src/castle_core/relations.py)."""

from __future__ import annotations

import pytest

import castle_core.config as C
from castle_core import relations as R
from castle_core.manifest import ProgramSpec, Requirement, SystemdDeployment


def _dep(program: str) -> SystemdDeployment:
    return SystemdDeployment.model_validate(
        {
            "manager": "systemd",
            "program": program,
            "run": {"launcher": "command", "argv": [program]},
        }
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


def test_requirements_merge_program_and_deployment_deduped() -> None:
    prog = ProgramSpec(
        id="web",
        system_dependencies=["pandoc"],
        requires=[Requirement(kind="deployment", ref="api", bind="API_URL")],
    )
    dep = SystemdDeployment.model_validate(
        {
            "manager": "systemd",
            "program": "web",
            "run": {"launcher": "command", "argv": ["web"]},
            "requires": [{"kind": "system", "ref": "pandoc"}],
        }  # dup of program's
    )
    cfg = _cfg(
        {"web": prog, "api": ProgramSpec(id="api")}, {"web": dep, "api": _dep("api")}
    )
    kinds = {(r.kind, r.ref) for r in R.requirements_of(cfg, "web")}
    assert kinds == {("system", "pandoc"), ("deployment", "api")}  # deduped


def test_deployment_edge_carries_bind_and_counts_fan_in() -> None:
    """A {kind: deployment} requirement becomes an edge (with bind), and the target's
    fan-in is the count of distinct dependents."""
    consumer = ProgramSpec(
        id="web", requires=[Requirement(kind="deployment", ref="api", bind="API_URL")]
    )
    consumer2 = ProgramSpec(
        id="cli", requires=[Requirement(kind="deployment", ref="api")]
    )
    cfg = _cfg(
        {"web": consumer, "cli": consumer2, "api": ProgramSpec(id="api")},
        {"web": _dep("web"), "cli": _dep("cli"), "api": _dep("api")},
    )
    m = R.build_model(cfg, check=False)
    edge = next(e for e in m.edges if e.src == "web" and e.dst == "api")
    assert edge.kind == "deployment" and edge.bind == "API_URL"
    api = next(n for n in m.nodes if n.name == "api")
    assert api.depended_on_by == 2  # web + cli


def test_functional_predicate_reports_unmet(monkeypatch: pytest.MonkeyPatch) -> None:
    """`functional?` is derived: a missing system package is unmet; a present
    deployment requirement is satisfied."""
    prog = ProgramSpec(
        id="web",
        system_dependencies=["pandoc"],
        requires=[Requirement(kind="deployment", ref="api")],
    )
    cfg = _cfg(
        {"web": prog, "api": ProgramSpec(id="api")},
        {"web": _dep("web"), "api": _dep("api")},
    )
    monkeypatch.setattr(R.shutil, "which", lambda _: None)  # nothing installed
    m = R.build_model(cfg, check=True)
    web = next(n for n in m.nodes if n.name == "web")
    assert web.unmet == ["system:pandoc"]  # deployment:api exists → satisfied
    assert web.functional is False


def test_missing_deployment_requirement_is_unmet() -> None:
    prog = ProgramSpec(id="web", requires=[Requirement(kind="deployment", ref="ghost")])
    cfg = _cfg({"web": prog}, {"web": _dep("web")})
    m = R.build_model(cfg, check=True)
    web = next(n for n in m.nodes if n.name == "web")
    assert web.unmet == ["deployment:ghost"] and web.functional is False
