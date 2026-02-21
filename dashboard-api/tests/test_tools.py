"""Tests for tools endpoints."""

from pathlib import Path

from fastapi.testclient import TestClient


class TestToolsList:
    """GET /tools endpoint tests."""

    def test_returns_grouped_tools(self, client: TestClient) -> None:
        """Returns tools grouped by source directory name."""
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        names = [cat["name"] for cat in data]
        assert "document" in names
        assert "utility" in names

    def test_groups_sorted(self, client: TestClient) -> None:
        """Groups are sorted alphabetically."""
        response = client.get("/tools")
        data = response.json()
        names = [cat["name"] for cat in data]
        assert names == sorted(names)

    def test_tool_fields(self, client: TestClient) -> None:
        """Tool summary has expected fields."""
        response = client.get("/tools")
        data = response.json()
        doc_group = next(c for c in data if c["name"] == "document")
        tool = next(t for t in doc_group["tools"] if t["id"] == "test-tool")
        assert tool["description"] == "Test tool"
        assert tool["source"] == "tools/document"
        assert tool["system_dependencies"] == ["pandoc"]
        # tool_type and category should not be present
        assert "tool_type" not in tool
        assert "category" not in tool

    def test_installed_flag(self, client: TestClient) -> None:
        """Tool with install.path is marked as installed."""
        response = client.get("/tools")
        data = response.json()
        doc_group = next(c for c in data if c["name"] == "document")
        tool = next(t for t in doc_group["tools"] if t["id"] == "test-tool")
        assert tool["installed"] is True

    def test_not_installed_flag(self, client: TestClient) -> None:
        """Tool without install.path is not marked as installed."""
        response = client.get("/tools")
        data = response.json()
        util_group = next(c for c in data if c["name"] == "utility")
        tool = next(t for t in util_group["tools"] if t["id"] == "test-tool-2")
        assert tool["installed"] is False

    def test_service_excluded(self, client: TestClient) -> None:
        """Services without tool spec are not listed."""
        response = client.get("/tools")
        data = response.json()
        all_ids = [t["id"] for cat in data for t in cat["tools"]]
        assert "test-svc" not in all_ids


class TestToolDetail:
    """GET /tools/{name} endpoint tests."""

    def test_get_tool(self, client: TestClient) -> None:
        """Returns detail for a known tool."""
        response = client.get("/tools/test-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-tool"
        assert data["source"] == "tools/document"
        assert data["system_dependencies"] == ["pandoc"]

    def test_docs_from_file(self, client: TestClient, castle_root: Path) -> None:
        """Reads documentation from .md file."""
        # Create doc file matching the source lookup (src/<dir_name>/<tool>.md)
        doc_dir = castle_root / "tools" / "document" / "src" / "document"
        doc_dir.mkdir(parents=True)
        (doc_dir / "test_tool.md").write_text(
            "---\ntitle: Test\n---\n\n# Test Tool\n\nUsage info here."
        )
        response = client.get("/tools/test-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["docs"] is not None
        assert "# Test Tool" in data["docs"]
        # Frontmatter should be stripped
        assert "---" not in data["docs"]

    def test_no_docs(self, client: TestClient) -> None:
        """Tool with no doc file returns null docs."""
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
