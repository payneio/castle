"""Tests for castle doctor."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.commands.doctor import run_doctor


class TestDoctor:
    """The diagnosis path — a bare, unconfigured node should fail loudly."""

    def test_bare_node_reports_problems(self, castle_root: Path, capsys: object) -> None:
        """No repo:, no control plane, nothing running → exit 1 with fix hints."""
        from castle_cli.config import load_config

        # The shared fixture has no repo: and no castle-gateway/api/dashboard, so the
        # Configuration and Runtime sections must FAIL. Patch where doctor imports it.
        with patch("castle_core.config.load_config", return_value=load_config(castle_root)):
            result = run_doctor(Namespace())

        assert result == 1
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "repo: not set" in out
        assert "control plane missing" in out
        # Every failing check offers a concrete next command.
        assert "castle apply" in out

    def test_load_failure_is_first_fail(self, capsys: object) -> None:
        """A castle.yaml that won't load is surfaced as a FAIL, not a traceback."""
        with patch("castle_core.config.load_config", side_effect=ValueError("bad yaml")):
            result = run_doctor(Namespace())

        assert result == 1
        out = capsys.readouterr().out  # type: ignore[attr-defined]
        assert "failed to load" in out
        assert "bad yaml" in out
