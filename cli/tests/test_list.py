"""Tests for castle list command."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.commands.list_cmd import run_list


class TestListCommand:
    """Tests for the list command."""

    def test_list_all(self, castle_root: Path, capsys: object) -> None:
        """List all components."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(role=None, json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-svc" in captured.out
        assert "test-tool" in captured.out

    def test_list_filter_role(self, castle_root: Path, capsys: object) -> None:
        """List filtered by role."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(role="tool", json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-tool" in captured.out
        assert "test-svc" not in captured.out

    def test_list_filter_service(self, castle_root: Path, capsys: object) -> None:
        """List filtered to services."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(role="service", json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-svc" in captured.out
        assert "test-tool" not in captured.out

    def test_list_json(self, castle_root: Path, capsys: object) -> None:
        """List output as JSON."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(role=None, json=True)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        data = json.loads(captured.out)
        names = [p["name"] for p in data]
        assert "test-svc" in names
        assert "test-tool" in names
        svc = next(p for p in data if p["name"] == "test-svc")
        assert "roles" in svc
        assert "service" in svc["roles"]
