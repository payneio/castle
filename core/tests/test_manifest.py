"""Tests for castle manifest models."""

from __future__ import annotations

import pytest
from castle_core.manifest import (
    BuildSpec,
    CaddySpec,
    ProgramSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    InstallSpec,
    JobSpec,
    ManageSpec,
    PathInstallSpec,
    ProxySpec,
    RunCommand,
    RunPython,
    RunRemote,
    ServiceSpec,
    SystemdSpec,
    ToolSpec,
)


class TestProgramSpec:
    """Tests for component (software catalog) model."""

    def test_minimal(self) -> None:
        """Minimal component just needs an id."""
        c = ProgramSpec(id="bare")
        assert c.description is None
        assert c.source is None
        assert c.install is None
        assert c.tool is None
        assert c.build is None

    def test_tool_component(self) -> None:
        """Component with tool and install specs."""
        c = ProgramSpec(
            id="my-tool",
            description="A tool",
            source="my-tool/",
            tool=ToolSpec(),
            install=InstallSpec(path=PathInstallSpec(alias="my-tool")),
        )
        assert c.source == "my-tool/"
        assert c.install.path.alias == "my-tool"

    def test_frontend_component(self) -> None:
        """Component with build spec."""
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


class TestServiceSpec:
    """Tests for service (long-running daemon) model."""

    def test_basic_service(self) -> None:
        """Service with run and expose."""
        s = ServiceSpec(
            id="svc",
            run=RunPython(runner="python", tool="svc"),
            expose=ExposeSpec(http=HttpExposeSpec(internal=HttpInternal(port=8000))),
        )
        assert s.run.runner == "python"
        assert s.expose.http.internal.port == 8000

    def test_service_with_component_ref(self) -> None:
        """Service can reference a component."""
        s = ServiceSpec(
            id="svc",
            component="my-component",
            run=RunPython(runner="python", tool="svc"),
        )
        assert s.component == "my-component"

    def test_service_with_proxy(self) -> None:
        """Service with proxy spec."""
        s = ServiceSpec(
            id="svc",
            run=RunPython(runner="python", tool="svc"),
            proxy=ProxySpec(caddy=CaddySpec(path_prefix="/svc")),
        )
        assert s.proxy.caddy.path_prefix == "/svc"

    def test_service_with_manage(self) -> None:
        """Service with systemd management."""
        s = ServiceSpec(
            id="svc",
            run=RunCommand(runner="command", argv=["bin"]),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        assert s.manage.systemd.enable is True

    def test_remote_with_systemd_raises(self) -> None:
        """Remote runner + systemd management is invalid."""
        with pytest.raises(
            ValueError, match="manage.systemd cannot be enabled for runner=remote"
        ):
            ServiceSpec(
                id="bad",
                run=RunRemote(runner="remote", base_url="http://example.com"),
                manage=ManageSpec(systemd=SystemdSpec()),
            )

    def test_no_run_is_invalid(self) -> None:
        """Service requires a run spec."""
        with pytest.raises(Exception):
            ServiceSpec(id="bad")


class TestJobSpec:
    """Tests for job (scheduled task) model."""

    def test_basic_job(self) -> None:
        """Job with run and schedule."""
        j = JobSpec(
            id="my-job",
            run=RunCommand(runner="command", argv=["backup"]),
            schedule="0 2 * * *",
        )
        assert j.schedule == "0 2 * * *"
        assert j.timezone == "America/Los_Angeles"

    def test_job_with_component_ref(self) -> None:
        """Job can reference a component."""
        j = JobSpec(
            id="sync",
            component="protonmail",
            run=RunCommand(runner="command", argv=["protonmail", "sync"]),
            schedule="*/5 * * * *",
        )
        assert j.component == "protonmail"

    def test_job_requires_schedule(self) -> None:
        """Job without schedule is invalid."""
        with pytest.raises(Exception):
            JobSpec(
                id="bad",
                run=RunCommand(runner="command", argv=["x"]),
            )

    def test_job_custom_timezone(self) -> None:
        """Job with custom timezone."""
        j = JobSpec(
            id="job",
            run=RunCommand(runner="command", argv=["x"]),
            schedule="0 0 * * *",
            timezone="UTC",
        )
        assert j.timezone == "UTC"


class TestModelSerialization:
    """Tests for model_dump behavior."""

    def test_dump_component_excludes_none(self) -> None:
        """model_dump with exclude_none drops None fields."""
        c = ProgramSpec(id="test", description="Test")
        data = c.model_dump(exclude_none=True, exclude={"id"})
        assert "description" in data
        assert "install" not in data
        assert "tool" not in data

    def test_dump_service(self) -> None:
        """Full service serializes correctly."""
        s = ServiceSpec(
            id="svc",
            description="A service",
            run=RunPython(runner="python", tool="svc"),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=9001), health_path="/health"
                )
            ),
            proxy=ProxySpec(caddy=CaddySpec(path_prefix="/svc")),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        data = s.model_dump(exclude_none=True, exclude={"id"})
        assert data["run"]["runner"] == "python"
        assert data["expose"]["http"]["internal"]["port"] == 9001
        assert data["proxy"]["caddy"]["path_prefix"] == "/svc"
