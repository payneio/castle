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
            args = Namespace(kind=None, stack=None, json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-svc" in captured.out
        assert "test-tool" in captured.out

    def test_list_filter_daemon(self, castle_root: Path, capsys: object) -> None:
        """--behavior filters the program catalog by its real behavior field."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(kind="service", stack=None, json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-daemon" in captured.out
        assert "test-tool" not in captured.out
        # Services/jobs are deployment views, not behaviors — hidden under a filter.
        assert "test-svc" not in captured.out

    def test_list_filter_tool(self, castle_root: Path, capsys: object) -> None:
        """List filtered to tools."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(kind="tool", stack=None, json=False)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "test-tool" in captured.out
        assert "test-svc" not in captured.out

    def test_list_jobs_are_deployments(self, castle_root: Path, capsys: object) -> None:
        """Jobs are a deployment view: shown unfiltered, hidden under a behavior filter."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            # Unfiltered: the job appears.
            run_list(Namespace(kind=None, stack=None, json=False))
            assert "test-job" in capsys.readouterr().out  # type: ignore[attr-defined]
            # Behavior filter targets the catalog, so jobs drop out.
            run_list(Namespace(kind="tool", stack=None, json=False))
            out = capsys.readouterr().out  # type: ignore[attr-defined]
            assert "test-job" not in out
            assert "test-svc" not in out
            assert "test-tool" in out

    def test_list_json(self, castle_root: Path, capsys: object) -> None:
        """JSON output tags each entry with its derived kind."""
        with patch("castle_cli.commands.list_cmd.load_config") as mock_load:
            from castle_cli.config import load_config

            mock_load.return_value = load_config(castle_root)
            args = Namespace(kind=None, stack=None, json=True)
            result = run_list(args)

        assert result == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        data = json.loads(captured.out)
        names = [p["name"] for p in data]
        assert "test-svc" in names
        assert "test-tool" in names
        svc = next(p for p in data if p["name"] == "test-svc")
        assert svc["kind"] == "service"
        # test-tool is a program deployed on PATH → its derived kind is `tool`.
        tool = next(p for p in data if p["name"] == "test-tool")
        assert tool["kind"] == "tool"
