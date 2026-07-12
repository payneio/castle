"""Tests for the stack-dependency endpoints (/stacks, /stacks/status, /stacks/{name})."""

from fastapi.testclient import TestClient

from castle_core.stacks import available_stacks


class TestStacks:
    def test_names_endpoint_stays_a_bare_list(self, client: TestClient) -> None:
        """`GET /stacks` keeps its back-compat string[] shape (the create-form select
        depends on it) even though the richer status lives at /stacks/status."""
        resp = client.get("/stacks")
        assert resp.status_code == 200
        assert resp.json() == available_stacks()

    def test_status_shape(self, client: TestClient) -> None:
        resp = client.get("/stacks/status")
        assert resp.status_code == 200
        body = resp.json()
        assert {s["name"] for s in body} == set(available_stacks())
        st = next(s for s in body if s["name"] == "python-fastapi")
        # python-fastapi declares uv; every tool carries its phase + fix.
        assert {"in_use", "ok", "tools", "programs", "verbs"} <= st.keys()
        uv = next(t for t in st["tools"] if t["command"] == "uv")
        assert uv["phase"] == "both" and uv["install_hint"]

    def test_detail_and_404(self, client: TestClient) -> None:
        assert client.get("/stacks/python-cli").json()["name"] == "python-cli"
        assert client.get("/stacks/nope").status_code == 404
