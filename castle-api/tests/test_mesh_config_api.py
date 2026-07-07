"""HTTP-layer tests for the /mesh/config endpoints (mesh-disabled paths).

The write/read-through-the-client behavior is covered by test_nats_integration;
here we pin the endpoint wiring when no mesh client is attached.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_config_reports_role_when_mesh_disabled(client: TestClient) -> None:
    r = client.get("/mesh/config")
    assert r.status_code == 200
    body = r.json()
    assert body["keys"] == []
    assert body["role"] == "follower"  # test-node has no explicit role


def test_get_missing_config_is_404(client: TestClient) -> None:
    assert client.get("/mesh/config/does/not/exist").status_code == 404


def test_write_without_mesh_is_503(client: TestClient) -> None:
    r = client.put("/mesh/config/fleet/motd", json={"value": "x"})
    assert r.status_code == 503
