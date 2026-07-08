"""POST /config/tools/{name}/schema — derive an Anthropic tool schema from --help,
and the tool_schema field round-tripping through the tool save path."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import json

from castle_core.config import load_config

from castle_api.config import settings


def _completion(args: dict) -> dict:
    """A minimal chat-completions response carrying an emit_tool_schema call."""
    return {
        "choices": [
            {"message": {"tool_calls": [
                {"function": {"name": "emit_tool_schema", "arguments": json.dumps(args)}}
            ]}}
        ]
    }


_BAD_CORE = {
    "name": "python3", "description": "d",
    "parameters": {"type": "object", "properties": {"m": {"type": "string", "enum": 3}}},
}
_GOOD_CORE = {
    "name": "python3", "description": "d",
    "parameters": {"type": "object", "properties": {"m": {"type": "string"}}},
}

# A tool whose program falls back to the tool name for its executable; `python3`
# is always on PATH, so derive succeeds deterministically.
_PY_TOOL = {"program": "python3", "manager": "path"}


class TestGenerateSchema:
    def test_generate_returns_draft_not_saved(
        self, client: TestClient, castle_root: Path
    ) -> None:
        client.put("/config/tools/python3", json={"config": _PY_TOOL})

        r = client.post("/config/tools/python3/schema")
        assert r.status_code == 200, r.text
        body = r.json()
        schema = body["schema"]
        # The stored draft is the neutral core (name/description/parameters),
        # rendered to a provider envelope only on read.
        assert schema["name"] == "python3"
        assert "parameters" in schema
        assert schema["parameters"]["properties"]

        # It's a draft: nothing persisted until the client saves it.
        cfg = load_config(castle_root)
        assert cfg.tools["python3"].tool_schema is None

    def test_unknown_tool_404(self, client: TestClient) -> None:
        r = client.post("/config/tools/nope-not-a-tool/schema")
        assert r.status_code == 404

    def test_validate_endpoint_valid(self, client: TestClient) -> None:
        r = client.post("/config/tools/schema/validate", json=_GOOD_CORE)
        assert r.status_code == 200
        assert r.json() == {"valid": True, "errors": []}

    def test_validate_endpoint_invalid(self, client: TestClient) -> None:
        r = client.post("/config/tools/schema/validate", json=_BAD_CORE)
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False and body["errors"]

    def test_uninstalled_executable_422(
        self, client: TestClient, castle_root: Path
    ) -> None:
        client.put(
            "/config/tools/ghosttool",
            json={"config": {"program": "ghosttool", "manager": "path"}},
        )
        r = client.post("/config/tools/ghosttool/schema")
        assert r.status_code == 422
        assert "PATH" in r.json()["detail"]

    def test_assist_disabled_returns_503(
        self, client: TestClient, castle_root: Path
    ) -> None:
        client.put("/config/tools/python3", json={"config": _PY_TOOL})
        # llm_enabled is False by default.
        r = client.post("/config/tools/python3/schema?assist=llm")
        assert r.status_code == 503
        assert "disabled" in r.json()["detail"]

    def test_assist_success_returns_draft(
        self, client: TestClient, castle_root: Path, monkeypatch
    ) -> None:
        client.put("/config/tools/python3", json={"config": _PY_TOOL})

        async def _fake_llm(help_text: str, name: str) -> dict:
            assert "python3" in help_text  # the recursive help was gathered
            return {
                "name": name,
                "description": "the python interpreter",
                "parameters": {
                    "type": "object",
                    "properties": {"script": {"type": "string"}},
                },
            }

        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr("castle_api.llm.generate_tool_schema_llm", _fake_llm)

        r = client.post("/config/tools/python3/schema?assist=llm")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["assist"] == "llm"
        assert body["schema"]["parameters"]["properties"] == {"script": {"type": "string"}}

    def test_assist_upstream_error_returns_502(
        self, client: TestClient, castle_root: Path, monkeypatch
    ) -> None:
        client.put("/config/tools/python3", json={"config": _PY_TOOL})

        async def _fail_llm(help_text: str, name: str) -> dict:
            from castle_api.llm import LLMAssistError

            raise LLMAssistError("litellm returned 500")

        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr("castle_api.llm.generate_tool_schema_llm", _fail_llm)

        r = client.post("/config/tools/python3/schema?assist=llm")
        assert r.status_code == 502
        assert "litellm" in r.json()["detail"]

    def test_assist_repairs_invalid_then_valid(
        self, client: TestClient, castle_root: Path, monkeypatch
    ) -> None:
        """A malformed first response (bad enum) is fed back and repaired."""
        client.put("/config/tools/python3", json={"config": _PY_TOOL})
        calls = {"n": 0}

        async def _fake_complete(messages: list, key: str) -> dict:
            calls["n"] += 1
            return _completion(_BAD_CORE if calls["n"] == 1 else _GOOD_CORE)

        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr("castle_api.llm.read_secret", lambda name: "k")
        monkeypatch.setattr("castle_api.llm._complete", _fake_complete)

        r = client.post("/config/tools/python3/schema?assist=llm")
        assert r.status_code == 200, r.text
        assert calls["n"] == 2  # repaired on the second attempt
        props = r.json()["schema"]["parameters"]["properties"]
        assert props == {"m": {"type": "string"}}

    def test_assist_unrepairable_returns_502(
        self, client: TestClient, castle_root: Path, monkeypatch
    ) -> None:
        """Persistently invalid output exhausts the repair budget → 502."""
        client.put("/config/tools/python3", json={"config": _PY_TOOL})

        async def _always_bad(messages: list, key: str) -> dict:
            return _completion(_BAD_CORE)

        monkeypatch.setattr(settings, "llm_enabled", True)
        monkeypatch.setattr("castle_api.llm.read_secret", lambda name: "k")
        monkeypatch.setattr("castle_api.llm._complete", _always_bad)

        r = client.post("/config/tools/python3/schema?assist=llm")
        assert r.status_code == 502
        assert "attempts" in r.json()["detail"]

    def test_schema_round_trips_through_save(
        self, client: TestClient, castle_root: Path
    ) -> None:
        """Saving a tool with tool_schema persists it (PATCH merge), and clearing
        it with null drops the field."""
        client.put("/config/tools/python3", json={"config": _PY_TOOL})
        schema = client.post("/config/tools/python3/schema").json()["schema"]

        client.put(
            "/config/tools/python3",
            json={"config": {"program": "python3", "tool_schema": schema}},
        )
        cfg = load_config(castle_root)
        assert cfg.tools["python3"].tool_schema is not None
        assert cfg.tools["python3"].tool_schema["name"] == "python3"

        # Clearing with null removes it (default None).
        client.put(
            "/config/tools/python3",
            json={"config": {"program": "python3", "tool_schema": None}},
        )
        cfg = load_config(castle_root)
        assert cfg.tools["python3"].tool_schema is None
