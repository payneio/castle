"""Fleet role (authority/follower) — config loading + registry round-trip."""

from __future__ import annotations

from pathlib import Path

import yaml
from castle_core.config import load_config
from castle_core.registry import (
    NodeConfig,
    NodeRegistry,
    load_registry,
    save_registry,
)


def _write_min_config(root: Path, role: str | None) -> None:
    data: dict = {"gateway": {"port": 18000}}
    if role is not None:
        data["role"] = role
    (root / "castle.yaml").write_text(yaml.safe_dump(data))


def test_role_defaults_to_follower(tmp_path: Path) -> None:
    _write_min_config(tmp_path, None)
    assert load_config(tmp_path).role == "follower"


def test_role_loaded_from_yaml(tmp_path: Path) -> None:
    _write_min_config(tmp_path, "authority")
    assert load_config(tmp_path).role == "authority"


def test_registry_role_round_trip(tmp_path: Path) -> None:
    reg = NodeRegistry(
        node=NodeConfig(hostname="civil", role="authority"), deployed={}
    )
    path = tmp_path / "registry.yaml"
    save_registry(reg, path)
    assert load_registry(path).node.role == "authority"


def test_registry_role_defaults_follower(tmp_path: Path) -> None:
    """A node with no explicit role round-trips as follower."""
    reg = NodeRegistry(node=NodeConfig(hostname="n"), deployed={})
    path = tmp_path / "registry.yaml"
    save_registry(reg, path)
    assert load_registry(path).node.role == "follower"
