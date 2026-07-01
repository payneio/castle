"""Tests for castle manifest models."""

from __future__ import annotations

import pytest
from castle_core.manifest import (
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
        # `kind` is derived at load time; a bare spec has none.
        assert c.kind is None
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

    def test_public_requires_proxy(self) -> None:
        """public without proxy is invalid (public needs an exposed process)."""
        with pytest.raises(ValueError, match="public requires proxy"):
            SystemdDeployment(
                id="bad",
                manager="systemd",
                run=RunPython(launcher="python", program="svc"),
                public=True,
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
            proxy=True,
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        data = s.model_dump(exclude_none=True, exclude={"id"})
        assert data["manager"] == "systemd"
        assert data["run"]["launcher"] == "python"
        assert data["expose"]["http"]["internal"]["port"] == 9001
        assert data["proxy"] is True
