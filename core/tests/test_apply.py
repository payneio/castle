"""Tests for `castle apply` convergence — the diff classification (plan mode).

Plan mode computes the activate/restart/deactivate/unchanged buckets without
writing or touching the runtime, so it's the deterministic way to test the diff.
`is_active` is patched to control the "before" state; unit bytes come from the
(empty) temp home, so a live systemd service with no prior unit reads as changed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import castle_core.deploy as deploy_mod
from castle_core.config import load_config
from castle_core.deploy import (
    _desired_registry,
    _gateway_would_change,
    _render_unit_preview,
    apply,
    generate_caddyfile_from_registry,
)
from castle_core.registry import Deployment


def _add_static(castle_root: Path, name: str = "test-static") -> None:
    """Write a caddy (static) program + deployment into an existing castle root."""
    (castle_root / "programs" / f"{name}.yaml").write_text(
        f"description: Static {name}\nsource: {castle_root / name}\n"
    )
    statics = castle_root / "deployments" / "statics"
    statics.mkdir(parents=True, exist_ok=True)
    (statics / f"{name}.yaml").write_text(
        f"program: {name}\nmanager: caddy\nroot: public\nreach: internal\n"
    )
    (castle_root / name / "public").mkdir(parents=True, exist_ok=True)


def _plan(castle_root: Path, active: dict[str, bool]):
    """Run apply(plan=True) with is_active stubbed to `active` (default False)."""
    with patch(
        "castle_core.lifecycle.is_active",
        side_effect=lambda n, k, c: active.get(n, False),
    ):
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
        tool = castle_root / "deployments" / "tools" / "test-tool.yaml"
        tool.write_text(tool.read_text() + "enabled: false\n")

        result = _plan(castle_root, active={"test-tool": True})

        assert "test-tool" in result.deactivated
        assert "test-tool" not in result.activated

    def test_disabled_inactive_is_unchanged(self, castle_root: Path) -> None:
        """enabled:false and already down → nothing to do."""
        tool = castle_root / "deployments" / "tools" / "test-tool.yaml"
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


class TestGatewayChange:
    """A caddy route change touches no systemd unit, so the activate/restart/
    deactivate reconcile can't see it. `gateway_changed` catches it by diffing the
    would-be Caddyfile/tunnel config against disk — otherwise a new/changed static
    route reports a false 'already converged'.

    SPECS_DIR is the real ~/.castle path (unpatched by the fixtures), so these
    redirect it to a temp dir to stay hermetic and never touch the live Caddyfile.
    """

    def test_new_route_reports_gateway_changed(
        self, castle_root: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """A static whose route isn't on disk yet → gateway_changed, even when the
        assets already exist so the deployment itself classifies 'unchanged'."""
        monkeypatch.setattr(deploy_mod, "SPECS_DIR", tmp_path / "specs")
        _add_static(castle_root)

        # Static is 'active' (built) → _classify buckets it 'unchanged'; the route is
        # still absent from the (missing) Caddyfile, so the gateway did change.
        result = _plan(castle_root, active={"test-static": True})

        assert "test-static" in result.unchanged
        assert result.gateway_changed is True
        assert result.changed is True

    def test_converged_caddyfile_is_not_changed(
        self, castle_root: Path, tmp_path: Path, monkeypatch
    ) -> None:
        """When the on-disk Caddyfile already matches the desired one, no change."""
        specs = tmp_path / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(deploy_mod, "SPECS_DIR", specs)
        _add_static(castle_root)
        config = load_config(castle_root)

        (specs / "Caddyfile").write_text(
            generate_caddyfile_from_registry(_desired_registry(config, None))
        )

        assert _gateway_would_change(config, None) is False


def test_render_unit_preview_none_for_non_systemd() -> None:
    """Non-systemd managers have no unit file — preview is None (never 'restart').

    A path deployment is unmanaged, so the renderer returns before touching config.
    """
    tool = Deployment(manager="path", run_cmd=[], kind="tool")
    assert _render_unit_preview(None, "x", tool, "tool") is None  # type: ignore[arg-type]
