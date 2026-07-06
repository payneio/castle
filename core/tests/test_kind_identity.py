"""A deployment's identity is (name, kind): a tool, a service, and a job can all be
named the same. These lock the per-kind stores, the storage round-trip, distinct
unit names (job-suffix), and the subdomain-uniqueness guard."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from castle_core.config import load_config, save_config
from castle_core.deploy import _build_deployed, _desired_unit_files
from castle_core.registry import NodeConfig, NodeRegistry


def _write(root: Path, store: str, name: str, spec: dict) -> None:
    d = root / "deployments" / store
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(yaml.dump(spec))


def _trio(root: Path) -> None:
    (root / "castle.yaml").write_text(yaml.dump({"gateway": {"port": 9000}}))
    _write(root, "services", "backup", {
        "manager": "systemd", "run": {"launcher": "python", "program": "backup"},
    })
    _write(root, "jobs", "backup", {
        "manager": "systemd", "run": {"launcher": "command", "argv": ["backup"]},
        "schedule": "0 2 * * *",
    })
    _write(root, "tools", "backup", {"manager": "path", "program": "backup"})


def test_same_name_across_kinds_loads_into_distinct_stores(tmp_path: Path) -> None:
    _trio(tmp_path)
    config = load_config(tmp_path)
    assert "backup" in config.services
    assert "backup" in config.jobs
    assert "backup" in config.tools
    # all_deployments yields all three with their kinds
    kinds = {kind for kind, name, _ in config.all_deployments() if name == "backup"}
    assert kinds == {"service", "job", "tool"}
    # deployments_named collects the trio
    assert {k for k, _ in config.deployments_named("backup")} == {"service", "job", "tool"}


def test_trio_round_trips_through_per_kind_dirs(tmp_path: Path) -> None:
    _trio(tmp_path)
    config = load_config(tmp_path)
    save_config(config)
    # written under per-kind subdirs
    assert (tmp_path / "deployments" / "services" / "backup.yaml").exists()
    assert (tmp_path / "deployments" / "jobs" / "backup.yaml").exists()
    assert (tmp_path / "deployments" / "tools" / "backup.yaml").exists()
    reloaded = load_config(tmp_path)
    assert "backup" in reloaded.services and "backup" in reloaded.jobs
    assert "backup" in reloaded.tools


def test_service_and_job_get_distinct_units(tmp_path: Path) -> None:
    _trio(tmp_path)
    config = load_config(tmp_path)
    registry = NodeRegistry(node=NodeConfig(hostname="h", gateway_port=9000))
    for _kind, name, spec in config.all_deployments():
        dep = _build_deployed(config, name, spec, [])
        dep.name = name
        registry.put(dep)
    units = _desired_unit_files(registry)
    # service keeps castle-<name>.service; job carries the -job marker; tool has none.
    assert "castle-backup.service" in units
    assert "castle-backup-job.service" in units
    assert "castle-backup-job.timer" in units


def test_service_and_static_cannot_share_a_subdomain(tmp_path: Path) -> None:
    (tmp_path / "castle.yaml").write_text(yaml.dump({"gateway": {"port": 9000}}))
    _write(tmp_path, "services", "app", {
        "manager": "systemd", "run": {"launcher": "python", "program": "app"},
        "reach": "internal", "expose": {"http": {"internal": {"port": 9001}}},
    })
    _write(tmp_path, "statics", "app", {"manager": "caddy", "program": "app", "root": "dist"})
    with pytest.raises(ValueError, match="subdomain 'app'"):
        load_config(tmp_path)
