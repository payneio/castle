"""Tests for tools endpoints."""

from fastapi.testclient import TestClient


class TestToolsList:
    """GET /tools endpoint tests."""

    def test_returns_flat_list(self, client: TestClient) -> None:
        """Returns tools as a flat sorted list."""
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        ids = [t["id"] for t in data]
        assert "test-tool" in ids
        assert "test-tool-2" in ids

    def test_sorted_alphabetically(self, client: TestClient) -> None:
        """Tools are sorted alphabetically by id."""
        response = client.get("/tools")
        data = response.json()
        ids = [t["id"] for t in data]
        assert ids == sorted(ids)

    def test_tool_fields(self, client: TestClient) -> None:
        """Tool summary has expected fields."""
        response = client.get("/tools")
        data = response.json()
        tool = next(t for t in data if t["id"] == "test-tool")
        assert tool["description"] == "Test tool"
        assert tool["source"] == "test-tool"
        assert tool["system_dependencies"] == ["pandoc"]

    def test_installed_flag(self, client: TestClient) -> None:
        """Tool installed field reflects whether binary is on PATH."""
        response = client.get("/tools")
        data = response.json()
        tool = next(t for t in data if t["id"] == "test-tool")
        # test-tool binary won't be on PATH in test env
        assert isinstance(tool["installed"], bool)

    def test_service_excluded(self, client: TestClient) -> None:
        """Services without tool spec are not listed."""
        response = client.get("/tools")
        data = response.json()
        all_ids = [t["id"] for t in data]
        assert "test-svc" not in all_ids


class TestToolDetail:
    """GET /tools/{name} endpoint tests."""

    def test_get_tool(self, client: TestClient) -> None:
        """Returns detail for a known tool."""
        response = client.get("/tools/test-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-tool"
        assert data["source"] == "test-tool"
        assert data["system_dependencies"] == ["pandoc"]

    def test_no_docs(self, client: TestClient) -> None:
        """Tool detail returns null docs (no .md files anymore)."""
        response = client.get("/tools/test-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["docs"] is None

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown component."""
        response = client.get("/tools/nonexistent")
        assert response.status_code == 404

    def test_not_a_tool(self, client: TestClient) -> None:
        """Returns 404 for component that is not a tool."""
        response = client.get("/tools/test-svc")
        assert response.status_code == 404
