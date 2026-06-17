"""Tests for `_build_run_cmd` — the python runner runs in place via `uv run`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from castle_core.deploy import _build_run_cmd
from castle_core.manifest import RunPython


def test_python_runner_uses_uv_run_from_source(tmp_path: Path) -> None:
    """A python service with a real source dir launches via `uv run --project`."""
    run = RunPython(runner="python", program="my-svc")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/uv"):
        cmd = _build_run_cmd("my-svc", run, {}, [], source_dir=tmp_path)
    assert cmd == [
        "/usr/bin/uv",
        "run",
        "--project",
        str(tmp_path),
        "--no-dev",
        "my-svc",
    ]


def test_python_runner_appends_args(tmp_path: Path) -> None:
    run = RunPython(runner="python", program="my-svc", args=["--flag", "x"])
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/uv"):
        cmd = _build_run_cmd("my-svc", run, {}, [], source_dir=tmp_path)
    assert cmd[-2:] == ["--flag", "x"]
    assert cmd[:5] == ["/usr/bin/uv", "run", "--project", str(tmp_path), "--no-dev"]


def test_python_runner_falls_back_to_path_without_source() -> None:
    """No resolvable source → PATH lookup of the script (no uv run)."""
    run = RunPython(runner="python", program="my-svc")
    with patch("castle_core.deploy.shutil.which", return_value="/home/u/.local/bin/my-svc"):
        cmd = _build_run_cmd("my-svc", run, {}, [], source_dir=None)
    assert cmd == ["/home/u/.local/bin/my-svc"]


def test_python_runner_warns_when_unresolvable() -> None:
    """No source and not on PATH → a warning, bare program name as last resort."""
    run = RunPython(runner="python", program="my-svc")
    messages: list[str] = []
    with patch("castle_core.deploy.shutil.which", return_value=None):
        cmd = _build_run_cmd("my-svc", run, {}, messages, source_dir=None)
    assert cmd == ["my-svc"]
    assert any("my-svc" in m for m in messages)
