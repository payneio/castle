"""Tests for castle info command."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


class TestInfoCommand:
    """Tests for the info command."""

    def test_info_service(self, castle_root: Path, capsys) -> None:
        """Show info for a service."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="test-svc", json=False))

        assert result == 0
        output = capsys.readouterr().out
        assert "test-svc" in output
        assert "daemon" in output
        assert "19000" in output

    def test_info_tool(self, castle_root: Path, capsys) -> None:
        """Show info for a tool."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="test-tool", json=False))

        assert result == 0
        output = capsys.readouterr().out
        assert "test-tool" in output
        assert "tool" in output

    def test_info_not_found(self, castle_root: Path, capsys) -> None:
        """Info for nonexistent component returns error."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="nope", json=False))

        assert result == 1
        output = capsys.readouterr().out
        assert "not found" in output

    def test_info_json_service(self, castle_root: Path, capsys) -> None:
        """--json produces valid JSON with service fields."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="test-svc", json=True))

        assert result == 0
        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["behavior"] == "daemon"
        assert data["service"]["expose"]["http"]["internal"]["port"] == 19000

    def test_info_shows_env(self, castle_root: Path, capsys) -> None:
        """Info displays environment variables."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="test-svc", json=False))

        assert result == 0
        output = capsys.readouterr().out
        assert "TEST_SVC_DATA_DIR" in output

    def test_info_shows_behavior(self, castle_root: Path, capsys) -> None:
        """Info displays behavior."""
        from castle_cli.config import load_config

        with patch("castle_cli.commands.info.load_config") as mock_load:
            mock_load.return_value = load_config(castle_root)

            from castle_cli.commands.info import run_info

            result = run_info(Namespace(project="test-svc", json=False))

        assert result == 0
        output = capsys.readouterr().out
        assert "behavior" in output
        assert "daemon" in output
