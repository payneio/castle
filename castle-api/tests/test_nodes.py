"""Tests for nodes endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient

from castle_core.registry import DeployedComponent, NodeConfig, NodeRegistry

from castle_api.mesh import MeshStateManager


class TestNodesList:
    """GET /nodes endpoint tests."""

    def test_returns_local_node(self, client: TestClient) -> None:
        """Always returns the local node."""
        response = client.get("/nodes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        local = data[0]
        assert local["hostname"] == "test-node"
        assert local["is_local"] is True
        assert local["online"] is True

    def test_local_node_counts(self, client: TestClient) -> None:
        """Local node has correct deployment counts."""
        response = client.get("/nodes")
        data = response.json()
        local = data[0]
        assert local["deployed_count"] == 1  # test-svc
        assert local["service_count"] == 1

    def test_includes_remote_nodes(self, client: TestClient, registry_path: Path) -> None:
        """Remote nodes from mesh state are included."""
        import castle_api.mesh as mesh_mod

        original = mesh_mod.mesh_state
        try:
            mgr = MeshStateManager()
            remote_reg = NodeRegistry(
                node=NodeConfig(hostname="devbox", gateway_port=9000),
                deployed={
                    "remote-svc": DeployedComponent(
                        runner="python",
                        run_cmd=["svc"],
                        port=9050,
                        behavior="daemon",
                    ),
                },
            )
            mgr.update_node("devbox", remote_reg)
            mesh_mod.mesh_state = mgr

            # Also patch the reference in the nodes module
            import castle_api.nodes as nodes_mod

            nodes_mod.mesh_state = mgr

            response = client.get("/nodes")
            data = response.json()
            hostnames = [n["hostname"] for n in data]
            assert "devbox" in hostnames
            devbox = next(n for n in data if n["hostname"] == "devbox")
            assert devbox["is_local"] is False
            assert devbox["deployed_count"] == 1
        finally:
            mesh_mod.mesh_state = original
            import castle_api.nodes as nodes_mod2

            nodes_mod2.mesh_state = original


class TestNodeDetail:
    """GET /nodes/{hostname} endpoint tests."""

    def test_local_node_detail(self, client: TestClient) -> None:
        """Returns local node detail with deployed components."""
        response = client.get("/nodes/test-node")
        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "test-node"
        assert data["is_local"] is True
        assert len(data["deployed"]) == 1
        assert data["deployed"][0]["id"] == "test-svc"
        assert data["deployed"][0]["node"] == "test-node"

    def test_unknown_node_returns_404(self, client: TestClient) -> None:
        """Returns 404 for unknown hostname."""
        response = client.get("/nodes/nonexistent")
        assert response.status_code == 404
