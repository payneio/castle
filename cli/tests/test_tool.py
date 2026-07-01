"""Tests for the `castle tool` lens."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


def _config(castle_root: Path):
    from castle_cli.config import load_config

    return load_config(castle_root)


class TestToolList:
    def test_list_includes_tool(self, castle_root: Path, capsys: object) -> None:
        with patch("castle_cli.commands.tool.load_config", return_value=_config(castle_root)):
            from castle_cli.commands.tool import run_tool_list

            rc = run_tool_list(Namespace(json=False))
        assert rc == 0
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "test-tool" in out
        # test-svc is a service (systemd), not a tool — must not appear.
        assert "test-svc" not in out

    def test_list_json_payload(self, castle_root: Path, capsys: object) -> None:
        with patch("castle_cli.commands.tool.load_config", return_value=_config(castle_root)):
            from castle_cli.commands.tool import run_tool_list

            rc = run_tool_list(Namespace(json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        tool = next(t for t in data if t["name"] == "test-tool")
        # The coding-assistant context payload.
        for key in ("name", "executables", "description", "installed", "source"):
            assert key in tool
        assert isinstance(tool["executables"], list) and tool["executables"]


class TestToolInfo:
    def test_info_json(self, castle_root: Path, capsys: object) -> None:
        with patch("castle_cli.commands.tool.load_config", return_value=_config(castle_root)):
            from castle_cli.commands.tool import run_tool_info

            rc = run_tool_info(Namespace(name="test-tool", json=True))
        assert rc == 0
        data = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        assert data["name"] == "test-tool"
        assert data["executables"]

    def test_info_rejects_non_tool(self, castle_root: Path, capsys: object) -> None:
        # test-svc is a service deployment, not a tool.
        with patch("castle_cli.commands.tool.load_config", return_value=_config(castle_root)):
            from castle_cli.commands.tool import run_tool_info

            rc = run_tool_info(Namespace(name="test-svc", json=False))
        assert rc == 1
