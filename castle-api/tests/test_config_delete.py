"""Tests for cascade program deletion via /config/programs/{name}."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestCascadeDelete:
    def test_blocked_without_cascade(self, client: TestClient) -> None:
        """A program with a referencing deployment refuses a plain delete (409)."""
        # test-tool (program) is referenced by test-tool (a path deployment).
        r = client.delete("/config/programs/test-tool")
        assert r.status_code == 409
        assert "cascade" in r.json()["detail"]

    def test_cascade_removes_program_and_deployment(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cascade=true tears down + removes the deployments and the program."""
        # Stub the runtime teardown so the test has no systemctl/deploy side effects.
        import castle_core.deploy as dp
        import castle_core.lifecycle as lc

        async def _noop(*_a: object, **_k: object) -> None:
            return None

        monkeypatch.setattr(lc, "deactivate", _noop)
        monkeypatch.setattr(dp, "deploy", lambda *_a, **_k: None)

        r = client.delete("/config/programs/test-tool?cascade=true")
        assert r.status_code == 200
        body = r.json()
        assert body["action"] == "deleted"
        assert "test-tool" in body["removed_deployments"]

        # The program is gone from the catalog.
        assert client.get("/programs/test-tool").status_code == 404
