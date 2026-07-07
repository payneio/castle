"""HTTP-layer tests for the node-override endpoints (file-backend paths).

The live OpenBao override round-trip is verified manually; here we pin the
file-backend behavior (overrides are an OpenBao-only feature).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_overrides_empty_on_file_backend(client: TestClient) -> None:
    r = client.get("/secrets/overrides")
    assert r.status_code == 200
    assert r.json() == {"overrides": {}}


def test_set_override_rejected_on_file_backend(client: TestClient) -> None:
    r = client.put("/secrets/overrides/primer/POSTGRES_PASSWORD", json={"value": "x"})
    assert r.status_code == 400


def test_get_missing_override_is_404(client: TestClient) -> None:
    assert client.get("/secrets/overrides/primer/NOPE").status_code == 404
