"""Tests for the unified active lifecycle (is_active dispatch)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from castle_core import lifecycle
from castle_core.config import load_config


class TestIsActive:
    def test_service_uses_systemctl(self, castle_root: Path) -> None:
        config = load_config(castle_root)
        with patch.object(lifecycle, "_systemctl_active", return_value=True) as mock:
            assert lifecycle.is_active("test-svc", config) is True
        mock.assert_called_once_with("castle-test-svc.service")

    def test_job_uses_timer(self, castle_root: Path) -> None:
        config = load_config(castle_root)
        with patch.object(lifecycle, "_systemctl_active", return_value=True) as mock:
            assert lifecycle.is_active("test-job", config) is True
        mock.assert_called_once_with("castle-test-job.timer")

    def test_tool_checks_path(self, castle_root: Path) -> None:
        config = load_config(castle_root)
        # give the tool a source so the tool branch is reachable
        config.programs["test-tool"].source = "/tmp/test-tool"
        with patch.object(lifecycle, "_on_path", return_value=True) as mock:
            assert lifecycle.is_active("test-tool", config) is True
        mock.assert_called_once_with("test-tool")

    def test_unknown_is_inactive(self, castle_root: Path) -> None:
        config = load_config(castle_root)
        assert lifecycle.is_active("does-not-exist", config) is False

    def test_path_deployment_checks_path(self, castle_root: Path) -> None:
        # A `manager: path` deployment (a tool) is active when on PATH.
        from castle_core.manifest import PathDeployment, ProgramSpec

        config = load_config(castle_root)
        config.programs["mytool"] = ProgramSpec(id="mytool", source="/tmp/mytool")
        config.deployments["mytool"] = PathDeployment(manager="path", program="mytool")
        with patch.object(lifecycle, "_on_path", return_value=True) as mock:
            assert lifecycle.is_active("mytool", config) is True
        mock.assert_called_once_with("mytool")

    def test_remote_deployment_is_active(self, castle_root: Path) -> None:
        # A remote deployment has no local process; the manager is `none` → available.
        from castle_core.manifest import RemoteDeployment

        config = load_config(castle_root)
        config.deployments["ext"] = RemoteDeployment(
            manager="none", program="ext", base_url="http://x"
        )
        assert lifecycle.is_active("ext", config) is True

    def test_static_deployment_active_when_dist_built(
        self, castle_root: Path, tmp_path: Path
    ) -> None:
        # A static (caddy) deployment is active once its served dir exists.
        from castle_core.manifest import CaddyDeployment, ProgramSpec

        config = load_config(castle_root)
        repo = tmp_path / "fe"
        config.programs["fe"] = ProgramSpec(id="fe", source=str(repo))
        config.deployments["fe"] = CaddyDeployment(
            manager="caddy", program="fe", root="dist"
        )
        # No dist yet → inactive (caddy manager checks the served dir)
        assert lifecycle.is_active("fe", config) is False
        # Built dist → served in place → active
        (repo / "dist").mkdir(parents=True)
        assert lifecycle.is_active("fe", config) is True
