"""Cross-node (remote) gateway routes + presence breaker."""

from __future__ import annotations

from pathlib import Path

import yaml
from castle_core.config import load_config
from castle_core.generators.caddyfile import compute_routes
from castle_core.registry import Deployment, NodeConfig, NodeRegistry


def _config_requiring_widget(root: Path) -> None:
    (root / "castle.yaml").write_text(yaml.safe_dump({"gateway": {"port": 18000}}))
    svc_dir = root / "deployments" / "services"
    svc_dir.mkdir(parents=True)
    (svc_dir / "consumer.yaml").write_text(
        yaml.safe_dump(
            {
                "description": "consumes a remote widget",
                "manager": "systemd",
                "run": {"launcher": "command", "argv": ["consumer"]},
                "requires": [{"kind": "deployment", "ref": "widget"}],
                "manage": {"systemd": {}},
            }
        )
    )


def _peer_with_widget(address: str | None) -> NodeRegistry:
    widget = Deployment(
        manager="systemd",
        launcher="python",
        run_cmd=[],
        name="widget",
        kind="service",
        port=9099,
        subdomain="widget",
        managed=True,
    )
    return NodeRegistry(
        node=NodeConfig(hostname="tower", address=address),
        deployed={NodeRegistry.key("service", "widget"): widget},
    )


def _local() -> NodeRegistry:
    return NodeRegistry(node=NodeConfig(hostname="civil"), deployed={})


def test_remote_route_emitted_for_consumed_peer_service(tmp_path: Path) -> None:
    _config_requiring_widget(tmp_path)
    config = load_config(tmp_path)
    routes = compute_routes(
        _local(), config, {"tower": _peer_with_widget("10.0.0.5")}
    )
    remote = [r for r in routes if r.kind == "remote"]
    assert len(remote) == 1
    assert remote[0].address == "widget"
    assert remote[0].target == "10.0.0.5:9099"
    assert remote[0].node == "tower"


def test_address_falls_back_to_hostname(tmp_path: Path) -> None:
    _config_requiring_widget(tmp_path)
    config = load_config(tmp_path)
    routes = compute_routes(_local(), config, {"tower": _peer_with_widget(None)})
    remote = [r for r in routes if r.kind == "remote"]
    assert remote[0].target == "tower:9099"


def test_breaker_no_route_when_peer_absent(tmp_path: Path) -> None:
    """Presence expiry removes the peer from remote_registries -> no route."""
    _config_requiring_widget(tmp_path)
    config = load_config(tmp_path)
    routes = compute_routes(_local(), config, {})  # no online peers
    assert not [r for r in routes if r.kind == "remote"]


def test_no_remote_route_for_unconsumed_service(tmp_path: Path) -> None:
    """A peer service nobody requires is not routed."""
    (tmp_path / "castle.yaml").write_text(yaml.safe_dump({"gateway": {"port": 18000}}))
    config = load_config(tmp_path)  # no requires anywhere
    routes = compute_routes(
        _local(), config, {"tower": _peer_with_widget("10.0.0.5")}
    )
    assert not [r for r in routes if r.kind == "remote"]
