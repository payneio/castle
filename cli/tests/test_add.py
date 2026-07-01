"""Tests for castle add — adopting existing repos as programs."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from castle_cli.config import load_config


def _run_add(castle_root: Path, **kwargs: object) -> object:
    with (
        patch("castle_cli.commands.add.load_config") as mock_load,
        patch("castle_cli.commands.add.save_config"),
    ):
        config = load_config(castle_root)
        mock_load.return_value = config
        from castle_cli.commands.add import run_add

        args = Namespace(name=None, description="", **kwargs)
        rc = run_add(args)
        return rc, config


class TestAdd:
    def test_adopt_python_path_assigns_stack(self, castle_root: Path, tmp_path: Path) -> None:
        repo = tmp_path / "mytool"
        repo.mkdir()
        (repo / "pyproject.toml").write_text('[project]\nname = "mytool"\ndependencies = []\n')
        rc, config = _run_add(castle_root, target=str(repo))
        assert rc == 0
        prog = config.programs["mytool"]
        assert prog.stack == "python-cli"  # detected
        assert prog.source == str(repo.resolve())

    def test_adopt_fastapi_detects_daemon(self, castle_root: Path, tmp_path: Path) -> None:
        repo = tmp_path / "svc"
        repo.mkdir()
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "svc"\ndependencies = ["fastapi>=0.1"]\n'
        )
        rc, config = _run_add(castle_root, target=str(repo))
        assert rc == 0
        # `add` adopts source only — no deployment yet (kind is a deployment
        # property); a fastapi project is detected as the python-fastapi stack.
        assert config.programs["svc"].stack == "python-fastapi"
        assert config.deployments_of("svc") == []

    def test_adopt_rust_declares_commands(self, castle_root: Path, tmp_path: Path) -> None:
        repo = tmp_path / "rusty"
        repo.mkdir()
        (repo / "Cargo.toml").write_text("[package]\nname = \"rusty\"\n")
        rc, config = _run_add(castle_root, target=str(repo))
        assert rc == 0
        prog = config.programs["rusty"]
        assert prog.stack is None  # no castle stack for rust
        # build lands in BuildSpec; other verbs in CommandsSpec
        assert prog.build is not None
        assert prog.build.commands == [["cargo", "build", "--release"]]
        assert prog.commands is not None
        assert prog.commands.run == [["cargo", "run"]]

    def test_adopt_git_url_records_repo(self, castle_root: Path) -> None:
        rc, config = _run_add(
            castle_root, target="https://github.com/someone/widget.git"
        )
        assert rc == 0
        prog = config.programs["widget"]
        assert prog.repo == "https://github.com/someone/widget.git"

    def test_missing_path_fails(self, castle_root: Path, tmp_path: Path) -> None:
        rc, _ = _run_add(castle_root, target=str(tmp_path / "nope"))
        assert rc == 1
