"""Tests for castle manifest models."""

from __future__ import annotations

import pytest
from castle_core.manifest import (
    Reach,
    BuildSpec,
    CaddyDeployment,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ManageSpec,
    PathDeployment,
    ProgramSpec,
    RunCommand,
    RunPython,
    RemoteDeployment,
    SystemdDeployment,
    SystemdSpec,
    kind_for,
)


class TestProgramSpec:
    """Tests for program (software catalog) model."""

    def test_minimal(self) -> None:
        """Minimal program just needs an id."""
        c = ProgramSpec(id="bare")
        assert c.description is None
        assert c.source is None
        # A program has no `kind` of its own — kind is a deployment property.
        assert not hasattr(c, "kind")
        assert c.build is None

    def test_tool_program(self) -> None:
        """Program with source and system_dependencies."""
        c = ProgramSpec(
            id="my-tool",
            description="A tool",
            source="my-tool/",
            system_dependencies=["pandoc"],
        )
        assert c.source == "my-tool/"
        assert c.system_dependencies == ["pandoc"]

    def test_frontend_program(self) -> None:
        """Program with build spec."""
        c = ProgramSpec(
            id="my-app",
            build=BuildSpec(commands=[["pnpm", "build"]], outputs=["dist/"]),
        )
        assert c.build.outputs == ["dist/"]

    def test_source_dir_from_source(self) -> None:
        """source_dir uses source field."""
        c = ProgramSpec(id="x", source="components/x/")
        assert c.source_dir == "components/x"

    def test_source_dir_none(self) -> None:
        """source_dir returns None when no source available."""
        c = ProgramSpec(id="x")
        assert c.source_dir is None


class TestSystemdDeployment:
    """Tests for the systemd deployment (service or job)."""

    def test_basic_service(self) -> None:
        """A systemd deployment with a launcher and expose is a service."""
        s = SystemdDeployment(
            id="svc",
            manager="systemd",
            run=RunPython(launcher="python", program="svc"),
            expose=ExposeSpec(http=HttpExposeSpec(internal=HttpInternal(port=8000))),
        )
        assert s.run.launcher == "python"
        assert s.expose.http.internal.port == 8000
        assert kind_for(s) == "service"

    def test_scheduled_is_a_job(self) -> None:
        """A systemd deployment with a schedule derives kind `job`."""
        j = SystemdDeployment(
            id="my-job",
            manager="systemd",
            run=RunCommand(launcher="command", argv=["backup"]),
            schedule="0 2 * * *",
        )
        assert j.schedule == "0 2 * * *"
        assert j.timezone == "America/Los_Angeles"
        assert kind_for(j) == "job"

    def test_program_ref(self) -> None:
        """A deployment can reference a program."""
        s = SystemdDeployment(
            id="svc",
            manager="systemd",
            program="my-program",
            run=RunPython(launcher="python", program="svc"),
        )
        assert s.program == "my-program"

    def test_with_manage(self) -> None:
        """A deployment with systemd management."""
        s = SystemdDeployment(
            id="svc",
            manager="systemd",
            run=RunCommand(launcher="command", argv=["bin"]),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        assert s.manage.systemd.enable is True

    def test_reach_ladder_and_accessors(self) -> None:
        """`reach` is canonical; the derived proxy/public accessors reflect it
        (public implies internal)."""
        # An exposed reach needs an expose block (see test_reach_requires_expose),
        # so give the base one; reach off doesn't, tested separately below.
        base = dict(
            id="svc",
            manager="systemd",
            run=RunPython(launcher="python", program="svc"),
            expose={"http": {"internal": {"port": 9001}}},
        )
        s_internal = SystemdDeployment(**base, reach=Reach.INTERNAL)
        assert s_internal.proxy is True and s_internal.public is False
        s_pub = SystemdDeployment(**base, reach=Reach.PUBLIC)
        assert s_pub.proxy is True and s_pub.public is True
        # reach off needs no expose block
        no_expose = dict(
            id="svc", manager="systemd", run=RunPython(launcher="python", program="svc")
        )
        assert SystemdDeployment(**no_expose, reach=Reach.OFF).reach == Reach.OFF

    def test_reach_requires_expose(self) -> None:
        """An exposed reach with no expose block is rejected (it would otherwise
        silently no-op — no route, no subdomain, no tunnel). Replaces the old
        'public requires proxy' guard."""
        base = dict(manager="systemd", run=RunPython(launcher="python", program="svc"))
        for reach in ("internal", "public"):
            with pytest.raises(ValueError, match="requires an `expose` block"):
                SystemdDeployment.model_validate({**base, "reach": reach})

    def test_tcp_exposure_is_not_http_exposed(self) -> None:
        """A raw-TCP service is reachable by name+port but never HTTP-routed."""
        base = dict(manager="systemd", run=RunCommand(launcher="command", argv=["pg"]))
        tcp = SystemdDeployment.model_validate(
            {**base, "reach": "internal", "expose": {"tcp": {"port": 5432}}}
        )
        assert tcp.tcp_port == 5432
        assert tcp.http_exposed is False  # <-- no Caddy route
        http = SystemdDeployment.model_validate(
            {**base, "reach": "internal", "expose": {"http": {"internal": {"port": 9001}}}}
        )
        assert http.http_exposed is True and http.tcp_port is None

    def test_expose_is_one_protocol(self) -> None:
        with pytest.raises(ValueError, match="http OR tcp"):
            SystemdDeployment.model_validate(
                {
                    "manager": "systemd",
                    "run": RunCommand(launcher="command", argv=["x"]),
                    "expose": {"http": {"internal": {"port": 1}}, "tcp": {"port": 2}},
                }
            )

    def test_public_tcp_guarded(self) -> None:
        """reach: public on a raw-TCP service is rejected until step 5 lands."""
        with pytest.raises(ValueError, match="public for a raw-TCP"):
            SystemdDeployment.model_validate(
                {
                    "manager": "systemd",
                    "run": RunCommand(launcher="command", argv=["x"]),
                    "reach": "public",
                    "expose": {"tcp": {"port": 5432}},
                }
            )

    def test_no_run_is_invalid(self) -> None:
        """A systemd deployment requires a run (launch) spec."""
        with pytest.raises(Exception):
            SystemdDeployment(id="bad", manager="systemd")


class TestOtherManagers:
    """Tests for the non-systemd managers and derived kinds."""

    def test_caddy_is_static(self) -> None:
        c = CaddyDeployment(id="fe", manager="caddy", program="fe", root="dist")
        assert c.root == "dist"
        assert kind_for(c) == "static"

    def test_path_is_tool(self) -> None:
        p = PathDeployment(id="cli", manager="path", program="cli")
        assert kind_for(p) == "tool"

    def test_none_is_reference(self) -> None:
        r = RemoteDeployment(id="ext", manager="none", base_url="http://example.com")
        assert r.base_url == "http://example.com"
        assert kind_for(r) == "reference"


class TestModelSerialization:
    """Tests for model_dump behavior."""

    def test_dump_program_excludes_none(self) -> None:
        """model_dump with exclude_none drops None fields."""
        c = ProgramSpec(id="test", description="Test")
        data = c.model_dump(exclude_none=True, exclude={"id"})
        assert "description" in data
        assert "build" not in data

    def test_dump_service(self) -> None:
        """Full systemd deployment serializes correctly."""
        s = SystemdDeployment(
            id="svc",
            manager="systemd",
            description="A service",
            run=RunPython(launcher="python", program="svc"),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=9001), health_path="/health"
                )
            ),
            reach=Reach.INTERNAL,
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        data = s.model_dump(exclude_none=True, exclude={"id"})
        assert data["manager"] == "systemd"
        assert data["run"]["launcher"] == "python"
        assert data["expose"]["http"]["internal"]["port"] == 9001
        assert data["reach"] == "internal"
        assert "proxy" not in data  # derived accessor, not serialized
