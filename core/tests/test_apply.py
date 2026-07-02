"""Tests for `castle apply` convergence — the diff classification (plan mode).

Plan mode computes the activate/restart/deactivate/unchanged buckets without
writing or touching the runtime, so it's the deterministic way to test the diff.
`is_active` is patched to control the "before" state; unit bytes come from the
(empty) temp home, so a live systemd service with no prior unit reads as changed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from castle_core.deploy import _render_unit_preview, apply
from castle_core.registry import Deployment


def _plan(castle_root: Path, active: dict[str, bool]):
    """Run apply(plan=True) with is_active stubbed to `active` (default False)."""
    with patch("castle_core.lifecycle.is_active", side_effect=lambda n, c: active.get(n, False)):
        return apply(root=castle_root, plan=True)


class TestApplyPlan:
    def test_fresh_converge_activates_enabled(self, castle_root: Path) -> None:
        """Nothing running → every enabled deployment is 'activate'; no writes."""
        result = _plan(castle_root, active={})

        assert result.planned is True
        assert set(result.activated) == {"test-svc", "test-tool", "test-job"}
        assert result.deactivated == []
        assert result.restarted == []

    def test_disabled_active_deployment_deactivates(self, castle_root: Path) -> None:
        """A deployment with enabled:false that's currently up → 'deactivate'."""
        # Turn the tool off in config.
        tool = castle_root / "services" / "test-tool.yaml"
        tool.write_text(tool.read_text() + "enabled: false\n")

        result = _plan(castle_root, active={"test-tool": True})

        assert "test-tool" in result.deactivated
        assert "test-tool" not in result.activated

    def test_disabled_inactive_is_unchanged(self, castle_root: Path) -> None:
        """enabled:false and already down → nothing to do."""
        tool = castle_root / "services" / "test-tool.yaml"
        tool.write_text(tool.read_text() + "enabled: false\n")

        result = _plan(castle_root, active={})

        assert "test-tool" in result.unchanged
        assert "test-tool" not in result.deactivated

    def test_active_service_with_changed_unit_restarts(self, castle_root: Path) -> None:
        """An up systemd service whose rendered unit differs from disk → 'restart'.

        The temp home has no prior unit file (before-bytes = None), so any live
        systemd deployment classifies as changed → restart, not a silent no-op.
        """
        result = _plan(castle_root, active={"test-svc": True})

        assert "test-svc" in result.restarted
        assert "test-svc" not in result.activated
        assert result.changed is True


def test_render_unit_preview_none_for_non_systemd() -> None:
    """Non-systemd managers have no unit file — preview is None (never 'restart').

    A path deployment is unmanaged, so the renderer returns before touching config.
    """
    tool = Deployment(manager="path", run_cmd=[], kind="tool")
    assert _render_unit_preview(None, "x", tool, is_job=False) is None  # type: ignore[arg-type]
