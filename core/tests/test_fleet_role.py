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


def test_save_config_round_trips_role_and_secrets(tmp_path: Path) -> None:
    """save_config rewrites castle.yaml from scratch — it must re-emit `role` and
    preserve the `secrets:` block, or a save reverts the node to a file-backend
    follower (the regression this guards)."""
    from castle_core.config import load_config, save_config

    (tmp_path / "castle.yaml").write_text(
        yaml.safe_dump(
            {
                "gateway": {"port": 18000},
                "role": "authority",
                "secrets": {"backend": "openbao", "addr": "https://v:8200"},
            }
        )
    )
    save_config(load_config(tmp_path))
    reloaded = yaml.safe_load((tmp_path / "castle.yaml").read_text())
    assert reloaded.get("role") == "authority"
    assert reloaded.get("secrets", {}).get("backend") == "openbao"


def test_save_config_preserves_arbitrary_unmanaged_global(tmp_path: Path) -> None:
    """Any top-level key save_config doesn't model must survive a rewrite."""
    from castle_core.config import load_config, save_config

    (tmp_path / "castle.yaml").write_text(
        yaml.safe_dump(
            {"gateway": {"port": 18000}, "role": "authority", "future_thing": {"x": 1}}
        )
    )
    save_config(load_config(tmp_path))
    reloaded = yaml.safe_load((tmp_path / "castle.yaml").read_text())
    assert reloaded.get("future_thing") == {"x": 1}
    assert reloaded.get("role") == "authority"


def test_write_deployment_file_leaves_globals_untouched(castle_root: Path) -> None:
    """A scoped deployment write must not rewrite castle.yaml globals (the PATCH
    guarantee that stops a deployment edit from dropping role/secrets)."""
    from castle_core.config import load_config, write_deployment_file

    cy = castle_root / "castle.yaml"
    data = yaml.safe_load(cy.read_text())
    data["role"] = "authority"
    data["secrets"] = {"backend": "openbao"}
    cy.write_text(yaml.safe_dump(data))
    before = cy.read_text()

    config = load_config(castle_root)
    kind, name, _dep = next(iter(config.all_deployments()))
    write_deployment_file(config, kind, name)

    assert cy.read_text() == before  # globals byte-identical — nothing touched them


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
