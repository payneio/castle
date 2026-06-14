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

    def test_static_frontend_active_when_dist_built(self, castle_root: Path, tmp_path: Path) -> None:
        from castle_core.manifest import BuildSpec

        config = load_config(castle_root)
        repo = tmp_path / "fe"
        config.programs["fe"] = config.programs["test-tool"].model_copy(
            update={
                "id": "fe",
                "behavior": "frontend",
                "source": str(repo),
                "build": BuildSpec(commands=[["pnpm", "build"]], outputs=["dist"]),
            }
        )
        # No dist yet → inactive
        assert lifecycle.is_active("fe", config) is False
        # Built dist → served in place → active
        (repo / "dist").mkdir(parents=True)
        assert lifecycle.is_active("fe", config) is True
