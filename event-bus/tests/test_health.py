"""Tests for event-bus health endpoint."""

from fastapi.testclient import TestClient


class TestHealth:
    """Health endpoint tests."""

    def test_health(self, client: TestClient) -> None:
        """Health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
