"""Tests for the new per-program commands/repo fields on the programs API."""

from fastapi.testclient import TestClient


class TestProgramCommands:
    def test_wired_in_program_surfaces_commands_and_repo(self, client: TestClient) -> None:
        """A stack-less adopted program exposes its declared commands + repo."""
        resp = client.get("/programs")
        assert resp.status_code == 200
        progs = {p["id"]: p for p in resp.json()}
        assert "wired-in" in progs
        w = progs["wired-in"]
        assert w["stack"] is None
        assert w["repo"] == "https://github.com/someone/wired-in.git"
        assert w["commands"]["lint"] == [["make", "lint"]]
        assert w["commands"]["run"] == [["./bin/wired-in"]]

    def test_wired_in_actions_resolved_from_commands(self, client: TestClient) -> None:
        """available actions come from declared commands when there's no stack."""
        resp = client.get("/programs")
        w = next(p for p in resp.json() if p["id"] == "wired-in")
        # declared lint/test/run + the composite check (lint/test available)
        assert set(w["actions"]) >= {"lint", "test", "run"}
        assert "build" not in w["actions"]  # not declared, no stack

    def test_tools_via_behavior_filter(self, client: TestClient) -> None:
        """Tools are reached via /programs?behavior=tool (no dedicated /tools)."""
        resp = client.get("/programs", params={"behavior": "tool"})
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert "wired-in" in ids and "test-tool" in ids
