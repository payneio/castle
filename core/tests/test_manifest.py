"""Tests for castle manifest — role derivation, validation."""

from __future__ import annotations

import pytest
from castle_core.manifest import (
    BuildSpec,
    CaddySpec,
    ComponentManifest,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    InstallSpec,
    ManageSpec,
    PathInstallSpec,
    ProxySpec,
    Role,
    RunCommand,
    RunContainer,
    RunPythonUvTool,
    RunRemote,
    SystemdSpec,
    ToolSpec,
    TriggerSchedule,
)


class TestRoleDerivation:
    """Tests for computed role derivation."""

    def test_service_from_expose_http(self) -> None:
        """Component with expose.http gets SERVICE role."""
        m = ComponentManifest(
            id="svc",
            run=RunPythonUvTool(runner="python_uv_tool", tool="svc"),
            expose=ExposeSpec(
                http=HttpExposeSpec(internal=HttpInternal(port=8000))
            ),
        )
        assert Role.SERVICE in m.roles

    def test_tool_from_install_path(self) -> None:
        """Component with install.path gets TOOL role."""
        m = ComponentManifest(
            id="mytool",
            install=InstallSpec(path=PathInstallSpec(alias="mytool")),
        )
        assert Role.TOOL in m.roles

    def test_worker_from_systemd_without_http(self) -> None:
        """Component managed by systemd but no HTTP gets WORKER role."""
        m = ComponentManifest(
            id="worker",
            run=RunCommand(runner="command", argv=["worker-bin"]),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        assert Role.WORKER in m.roles
        assert Role.SERVICE not in m.roles

    def test_container_role(self) -> None:
        """Container runner gets CONTAINERIZED role."""
        m = ComponentManifest(
            id="container",
            run=RunContainer(runner="container", image="redis:7"),
        )
        assert Role.CONTAINERIZED in m.roles

    def test_remote_role(self) -> None:
        """Remote runner gets REMOTE role."""
        m = ComponentManifest(
            id="remote",
            run=RunRemote(runner="remote", base_url="http://example.com"),
        )
        assert Role.REMOTE in m.roles

    def test_job_from_schedule_trigger(self) -> None:
        """Component with schedule trigger gets JOB role."""
        m = ComponentManifest(
            id="job",
            run=RunCommand(runner="command", argv=["backup"]),
            triggers=[TriggerSchedule(cron="0 * * * *")],
        )
        assert Role.JOB in m.roles

    def test_frontend_from_build(self) -> None:
        """Component with build outputs gets FRONTEND role."""
        m = ComponentManifest(
            id="frontend",
            run=RunCommand(runner="command", argv=["serve"]),
            build=BuildSpec(commands=[["pnpm", "build"]], outputs=["dist/"]),
        )
        assert Role.FRONTEND in m.roles

    def test_tool_from_tool_spec(self) -> None:
        """Component with tool spec gets TOOL role."""
        m = ComponentManifest(
            id="docx2md",
            tool=ToolSpec(source="docx2md/"),
        )
        assert Role.TOOL in m.roles

    def test_tool_spec_without_install(self) -> None:
        """Tool spec alone is enough for TOOL role, no install.path needed."""
        m = ComponentManifest(
            id="my-tool",
            tool=ToolSpec(),
        )
        assert Role.TOOL in m.roles

    def test_fallback_to_tool(self) -> None:
        """Component with no indicators defaults to TOOL."""
        m = ComponentManifest(id="bare")
        assert m.roles == [Role.TOOL]

    def test_multiple_roles(self) -> None:
        """Component can have multiple roles."""
        m = ComponentManifest(
            id="multi",
            run=RunPythonUvTool(runner="python_uv_tool", tool="multi"),
            expose=ExposeSpec(
                http=HttpExposeSpec(internal=HttpInternal(port=8000))
            ),
            install=InstallSpec(path=PathInstallSpec(alias="multi")),
        )
        assert Role.SERVICE in m.roles
        assert Role.TOOL in m.roles

    def test_systemd_with_http_is_service_not_worker(self) -> None:
        """Systemd + HTTP = SERVICE, not WORKER."""
        m = ComponentManifest(
            id="svc",
            run=RunPythonUvTool(runner="python_uv_tool", tool="svc"),
            expose=ExposeSpec(
                http=HttpExposeSpec(internal=HttpInternal(port=8000))
            ),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        assert Role.SERVICE in m.roles
        assert Role.WORKER not in m.roles


class TestConsistencyValidation:
    """Tests for model validation."""

    def test_remote_with_systemd_raises(self) -> None:
        """Remote runner + systemd management is invalid."""
        with pytest.raises(ValueError, match="manage.systemd cannot be enabled for runner=remote"):
            ComponentManifest(
                id="bad",
                run=RunRemote(runner="remote", base_url="http://example.com"),
                manage=ManageSpec(systemd=SystemdSpec()),
            )

    def test_no_run_is_valid(self) -> None:
        """Component with no run spec is valid (registration-only)."""
        m = ComponentManifest(id="reg-only", description="Just registered")
        assert m.run is None
        assert m.roles == [Role.TOOL]


class TestModelSerialization:
    """Tests for model_dump behavior."""

    def test_dump_excludes_none(self) -> None:
        """model_dump with exclude_none drops None fields."""
        m = ComponentManifest(id="test", description="Test")
        data = m.model_dump(exclude_none=True, exclude={"id", "roles"})
        assert "description" in data
        assert "run" not in data
        assert "manage" not in data

    def test_dump_service(self) -> None:
        """Full service manifest serializes correctly."""
        m = ComponentManifest(
            id="svc",
            description="A service",
            run=RunPythonUvTool(runner="python_uv_tool", tool="svc", cwd="svc"),
            expose=ExposeSpec(
                http=HttpExposeSpec(
                    internal=HttpInternal(port=9001), health_path="/health"
                )
            ),
            proxy=ProxySpec(caddy=CaddySpec(path_prefix="/svc")),
            manage=ManageSpec(systemd=SystemdSpec()),
        )
        data = m.model_dump(exclude_none=True, exclude={"id", "roles"})
        assert data["run"]["runner"] == "python_uv_tool"
        assert data["expose"]["http"]["internal"]["port"] == 9001
        assert data["proxy"]["caddy"]["path_prefix"] == "/svc"
