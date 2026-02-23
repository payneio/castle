"""Tests for MeshStateManager."""

import time

from castle_core.registry import DeployedComponent, NodeConfig, NodeRegistry

from castle_api.mesh import STALE_TTL_SECONDS, MeshStateManager, RemoteNode


def _make_registry(hostname: str, deployed: dict | None = None) -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(hostname=hostname, gateway_port=9000),
        deployed=deployed or {},
    )


class TestRemoteNode:
    """RemoteNode staleness tracking."""

    def test_fresh_node_not_stale(self) -> None:
        node = RemoteNode(registry=_make_registry("a"))
        assert not node.is_stale

    def test_old_node_is_stale(self) -> None:
        node = RemoteNode(
            registry=_make_registry("a"),
            last_seen=time.time() - STALE_TTL_SECONDS - 1,
        )
        assert node.is_stale


class TestMeshStateManager:
    """MeshStateManager add/remove/stale operations."""

    def test_update_and_get(self) -> None:
        mgr = MeshStateManager()
        reg = _make_registry("devbox")
        mgr.update_node("devbox", reg)
        node = mgr.get_node("devbox")
        assert node is not None
        assert node.registry.node.hostname == "devbox"
        assert node.online is True

    def test_set_offline(self) -> None:
        mgr = MeshStateManager()
        mgr.update_node("devbox", _make_registry("devbox"))
        mgr.set_offline("devbox")
        node = mgr.get_node("devbox")
        assert node is not None
        assert node.online is False

    def test_remove_node(self) -> None:
        mgr = MeshStateManager()
        mgr.update_node("devbox", _make_registry("devbox"))
        mgr.remove_node("devbox")
        assert mgr.get_node("devbox") is None

    def test_remove_nonexistent_is_safe(self) -> None:
        mgr = MeshStateManager()
        mgr.remove_node("nope")  # should not raise

    def test_all_nodes_excludes_stale(self) -> None:
        mgr = MeshStateManager()
        mgr.update_node("fresh", _make_registry("fresh"))
        mgr._nodes["stale"] = RemoteNode(
            registry=_make_registry("stale"),
            last_seen=time.time() - STALE_TTL_SECONDS - 1,
        )
        result = mgr.all_nodes()
        assert "fresh" in result
        assert "stale" not in result

    def test_all_nodes_includes_stale_when_requested(self) -> None:
        mgr = MeshStateManager()
        mgr._nodes["stale"] = RemoteNode(
            registry=_make_registry("stale"),
            last_seen=time.time() - STALE_TTL_SECONDS - 1,
        )
        result = mgr.all_nodes(include_stale=True)
        assert "stale" in result

    def test_prune_stale(self) -> None:
        mgr = MeshStateManager()
        mgr.update_node("fresh", _make_registry("fresh"))
        mgr._nodes["stale"] = RemoteNode(
            registry=_make_registry("stale"),
            last_seen=time.time() - STALE_TTL_SECONDS - 1,
        )
        pruned = mgr.prune_stale()
        assert pruned == ["stale"]
        assert mgr.get_node("stale") is None
        assert mgr.get_node("fresh") is not None

    def test_update_replaces_existing(self) -> None:
        mgr = MeshStateManager()
        mgr.update_node("devbox", _make_registry("devbox"))
        new_reg = _make_registry(
            "devbox",
            {"svc": DeployedComponent(runner="python", run_cmd=["svc"])},
        )
        mgr.update_node("devbox", new_reg)
        node = mgr.get_node("devbox")
        assert node is not None
        assert "svc" in node.registry.deployed
