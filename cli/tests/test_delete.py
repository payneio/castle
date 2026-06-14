"""Tests for castle delete."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.config import load_config


def _run_delete(castle_root: Path, **kwargs: object) -> object:
    with (
        patch("castle_cli.commands.delete.load_config") as mock_load,
        patch("castle_cli.commands.delete.save_config"),
    ):
        config = load_config(castle_root)
        mock_load.return_value = config
        from castle_cli.commands.delete import run_delete

        args = Namespace(source=False, yes=True, **kwargs)
        rc = run_delete(args)
        return rc, config


class TestDelete:
    def test_delete_program(self, castle_root: Path) -> None:
        rc, config = _run_delete(castle_root, name="test-tool")
        assert rc == 0
        assert "test-tool" not in config.programs

    def test_delete_unknown_fails(self, castle_root: Path) -> None:
        rc, _ = _run_delete(castle_root, name="does-not-exist")
        assert rc == 1

    def test_delete_source_removes_dir(self, castle_root: Path, tmp_path: Path) -> None:
        # Point a program's source at a real temp dir, then delete with --source.
        src = tmp_path / "victim"
        src.mkdir()
        (src / "file.txt").write_text("x")
        with (
            patch("castle_cli.commands.delete.load_config") as mock_load,
            patch("castle_cli.commands.delete.save_config"),
        ):
            config = load_config(castle_root)
            config.programs["test-tool"].source = str(src)
            mock_load.return_value = config
            from castle_cli.commands.delete import run_delete

            rc = run_delete(Namespace(name="test-tool", source=True, yes=True))
        assert rc == 0
        assert not src.exists()

    def test_abort_without_yes_and_no_input(self, castle_root: Path) -> None:
        # No --yes and no stdin → aborts safely (returns 1, leaves entry).
        with (
            patch("castle_cli.commands.delete.load_config") as mock_load,
            patch("castle_cli.commands.delete.save_config"),
            patch("builtins.input", side_effect=EOFError),
        ):
            config = load_config(castle_root)
            mock_load.return_value = config
            from castle_cli.commands.delete import run_delete

            rc = run_delete(Namespace(name="test-tool", source=False, yes=False))
        assert rc == 1
        assert "test-tool" in config.programs
