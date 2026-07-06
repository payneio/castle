"""Tests for convergent-deploy orphan pruning (prefix-based)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from castle_core import deploy as deploy_mod
from castle_core.deploy import _desired_unit_files, _prune_orphans
from castle_core.registry import Deployment, NodeConfig, NodeRegistry


def _svc(managed: bool = True, schedule: str | None = None) -> Deployment:
    return Deployment(
        manager="systemd",
        launcher="python",
        run_cmd=["x"],
        env={},
        managed=managed,
        schedule=schedule,
        kind="job" if schedule else "service",
    )


def _registry(**deployed: Deployment) -> NodeRegistry:
    reg = NodeRegistry(node=NodeConfig(castle_root="/x", gateway_port=9000))
    for name, d in deployed.items():
        d.name = name
        reg.put(d)
    return reg


def _touch(d: Path, *names: str) -> None:
    for n in names:
        (d / n).write_text("[Unit]\n")


class TestDesiredUnitFiles:
    def test_managed_service_yields_service_file(self) -> None:
        reg = _registry(foo=_svc())
        assert _desired_unit_files(reg) == {"castle-foo.service"}

    def test_scheduled_job_yields_service_and_timer(self) -> None:
        reg = _registry(job=_svc(schedule="0 2 * * *"))
        assert _desired_unit_files(reg) == {"castle-job-job.service", "castle-job-job.timer"}

    def test_unmanaged_excluded(self) -> None:
        reg = _registry(foo=_svc(managed=False))
        assert _desired_unit_files(reg) == set()


class TestPruneOrphans:
    def test_removes_orphan_keeps_desired(self, tmp_path: Path) -> None:
        units = tmp_path / "systemd"
        units.mkdir()
        # keep-me is in the registry; gone is not; gone.timer is also orphaned
        _touch(units, "castle-keep.service", "castle-gone.service", "castle-gone.timer")
        reg = _registry(keep=_svc())
        msgs: list[str] = []
        with (
            patch.object(deploy_mod, "SYSTEMD_USER_DIR", units),
            patch.object(deploy_mod.subprocess, "run") as mock_run,
        ):
            _prune_orphans(reg, msgs)
        assert (units / "castle-keep.service").exists()
        assert not (units / "castle-gone.service").exists()
        assert not (units / "castle-gone.timer").exists()
        # stop + disable were invoked for each removed unit
        assert mock_run.call_count >= 2
        assert any("castle-gone.service" in m for m in msgs)

    def test_unscheduled_job_drops_stale_timer_keeps_service(self, tmp_path: Path) -> None:
        units = tmp_path / "systemd"
        units.mkdir()
        _touch(units, "castle-job.service", "castle-job.timer")
        # job is still managed but no longer scheduled → its timer is now an orphan
        reg = _registry(job=_svc(schedule=None))
        with (
            patch.object(deploy_mod, "SYSTEMD_USER_DIR", units),
            patch.object(deploy_mod.subprocess, "run"),
        ):
            _prune_orphans(reg, [])
        assert (units / "castle-job.service").exists()
        assert not (units / "castle-job.timer").exists()

    def test_demoted_to_unmanaged_is_pruned(self, tmp_path: Path) -> None:
        units = tmp_path / "systemd"
        units.mkdir()
        _touch(units, "castle-foo.service")
        reg = _registry(foo=_svc(managed=False))  # still in registry but unmanaged
        with (
            patch.object(deploy_mod, "SYSTEMD_USER_DIR", units),
            patch.object(deploy_mod.subprocess, "run"),
        ):
            _prune_orphans(reg, [])
        assert not (units / "castle-foo.service").exists()
