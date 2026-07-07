"""Tests for castle doctor."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest
from castle_cli.commands.doctor import FAIL, OK, WARN, _check_configuration, run_doctor


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


class TestDataDirChecks:
    """The drift-prevention checks: data_dir must be writable, and a CASTLE_DATA_DIR env
    override (the one way the CLI and api can still diverge) must be surfaced."""

    def _config(self, castle_root: Path):
        from castle_cli.config import load_config

        return load_config(castle_root)

    def test_writable_dir_ok_no_warn(
        self, castle_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CASTLE_DATA_DIR", raising=False)
        monkeypatch.delenv("CASTLE_REPOS_DIR", raising=False)
        cfg = self._config(castle_root)
        cfg.data_dir = tmp_path  # exists + writable
        checks = _check_configuration(cfg)
        by_label = {c.label: c for c in checks}
        assert by_label["data dir writable"].status == OK
        assert not any("overrides castle.yaml" in c.label for c in checks)

    def test_missing_dir_fails_with_hint(
        self, castle_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CASTLE_DATA_DIR", raising=False)
        cfg = self._config(castle_root)
        missing = tmp_path / "nope"
        cfg.data_dir = missing
        fail = next(
            c for c in _check_configuration(cfg) if "data dir" in c.label and c.status == FAIL
        )
        assert str(missing) in fail.detail
        assert fail.hint  # offers a concrete fix

    def test_env_override_warns(
        self, castle_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A CASTLE_DATA_DIR env var overrides the single-source-of-truth file — the
        exact CLI/api divergence we fixed. Doctor must WARN."""
        monkeypatch.setenv("CASTLE_DATA_DIR", str(tmp_path))
        cfg = self._config(castle_root)
        cfg.data_dir = tmp_path
        warn = next(c for c in _check_configuration(cfg) if "overrides castle.yaml" in c.label)
        assert warn.status == WARN
        assert "CASTLE_DATA_DIR" in warn.detail
