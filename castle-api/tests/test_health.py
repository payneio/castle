"""Tests for castle-api health endpoint."""

from fastapi.testclient import TestClient


class TestHealth:
    """Health endpoint tests."""

    def test_health(self, client: TestClient) -> None:
        """Health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestComponents:
    """Component list endpoint tests."""

    def test_list_components(self, client: TestClient) -> None:
        """Returns all registered components."""
        response = client.get("/components")
        assert response.status_code == 200
        data = response.json()
        names = [c["id"] for c in data]
        assert "test-svc" in names
        assert "test-tool" in names

    def test_service_has_port(self, client: TestClient) -> None:
        """Service component includes port info."""
        response = client.get("/components")
        data = response.json()
        svc = next(c for c in data if c["id"] == "test-svc")
        assert svc["port"] == 19000
        assert svc["health_path"] == "/health"
        assert svc["proxy_path"] == "/test-svc"
        assert svc["managed"] is True
        assert "service" in svc["roles"]

    def test_tool_has_no_port(self, client: TestClient) -> None:
        """Tool component has no port."""
        response = client.get("/components")
        data = response.json()
        tool = next(c for c in data if c["id"] == "test-tool")
        assert tool["port"] is None
        assert "tool" in tool["roles"]


class TestComponentDetail:
    """Component detail endpoint tests."""

    def test_get_component(self, client: TestClient) -> None:
        """Returns detailed info for a component."""
        response = client.get("/components/test-svc")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-svc"
        assert "manifest" in data
        assert data["manifest"]["runner"] == "python_uv_tool"

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown component."""
        response = client.get("/components/nonexistent")
        assert response.status_code == 404


class TestGateway:
    """Gateway info endpoint tests."""

    def test_gateway_info(self, client: TestClient) -> None:
        """Returns gateway configuration from registry."""
        response = client.get("/gateway")
        assert response.status_code == 200
        data = response.json()
        assert data["port"] == 9000
        # Registry has 1 deployed component (test-svc)
        assert data["component_count"] == 1
        assert data["service_count"] == 1
        assert data["managed_count"] == 1
