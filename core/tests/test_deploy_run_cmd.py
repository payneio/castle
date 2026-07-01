"""Tests for `_build_run_cmd` — the python runner runs in place via `uv run`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from castle_core.deploy import _build_run_cmd, _build_stop_cmd
from castle_core.manifest import RunCompose, RunContainer, RunNode, RunPython


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
    with patch(
        "castle_core.deploy.shutil.which", return_value="/home/u/.local/bin/my-svc"
    ):
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


def test_node_runner_bakes_source_dir(tmp_path: Path) -> None:
    """A node service runs the script in its source dir via `--dir` (no unit cwd)."""
    run = RunNode(runner="node", script="gateway:watch:raw", package_manager="pnpm")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/pnpm"):
        cmd = _build_run_cmd("oc", run, {}, [], source_dir=tmp_path)
    assert cmd == ["/usr/bin/pnpm", "--dir", str(tmp_path), "run", "gateway:watch:raw"]


def test_node_runner_appends_args(tmp_path: Path) -> None:
    run = RunNode(
        runner="node", script="start", package_manager="pnpm", args=["--port", "18789"]
    )
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/pnpm"):
        cmd = _build_run_cmd("oc", run, {}, [], source_dir=tmp_path)
    assert cmd == [
        "/usr/bin/pnpm",
        "--dir",
        str(tmp_path),
        "run",
        "start",
        "--port",
        "18789",
    ]


def test_node_runner_without_source_omits_dir() -> None:
    """No resolvable source → bare `pnpm run` (package manager still PATH-resolved)."""
    run = RunNode(runner="node", script="start", package_manager="pnpm")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/pnpm"):
        cmd = _build_run_cmd("oc", run, {}, [], source_dir=None)
    assert cmd == ["/usr/bin/pnpm", "run", "start"]


def test_container_secrets_use_env_file_not_argv() -> None:
    """Secrets go through --env-file; plain vars stay as -e; no secret in argv."""
    run = RunContainer(runner="container", image="img:latest", env={"PLAIN": "1"})
    env_file = Path("/home/u/.castle/secrets/env/castle-svc.service.env")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        cmd = _build_run_cmd("svc", run, {"PORT": "9001"}, [], secret_env_file=env_file)
    joined = " ".join(cmd)
    assert "--env-file" in cmd
    assert str(env_file) in cmd
    # plain (non-secret) vars are still inlined as -e
    assert "-e" in cmd and "PORT=9001" in joined and "PLAIN=1" in joined
    # no resolved secret value leaks into argv (only the file path is referenced)
    assert "SECRET=" not in joined


def test_container_without_secrets_has_no_env_file() -> None:
    run = RunContainer(runner="container", image="img:latest")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        cmd = _build_run_cmd("svc", run, {}, [], secret_env_file=None)
    assert "--env-file" not in cmd


def test_compose_runner_up_with_resolved_file(tmp_path: Path) -> None:
    """A compose service runs `docker compose -p <project> -f <abs-file> up`."""
    run = RunCompose(runner="compose", file="docker-compose.yml")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        cmd = _build_run_cmd("supabase", run, {}, [], source_dir=tmp_path)
    assert cmd == [
        "/usr/bin/docker",
        "compose",
        "-p",
        "castle-supabase",
        "-f",
        str(tmp_path / "docker-compose.yml"),
        "up",
    ]


def test_compose_runner_secrets_never_hit_argv(tmp_path: Path) -> None:
    """Compose reads env from the process (systemd), not --env-file/-e — argv is clean."""
    run = RunCompose(runner="compose", file="docker-compose.yml")
    env_file = Path("/home/u/.castle/secrets/env/castle-supabase.service.env")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        cmd = _build_run_cmd(
            "supabase", run, {"PORT": "8000"}, [], source_dir=tmp_path,
            secret_env_file=env_file,
        )
    joined = " ".join(cmd)
    assert "--env-file" not in cmd
    assert "-e" not in cmd
    assert str(env_file) not in joined


def test_compose_project_name_override(tmp_path: Path) -> None:
    run = RunCompose(runner="compose", file="stack.yml", project_name="myproj")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        cmd = _build_run_cmd("s", run, {}, [], source_dir=tmp_path)
    assert cmd[:6] == [
        "/usr/bin/docker", "compose", "-p", "myproj", "-f", str(tmp_path / "stack.yml"),
    ]


def test_compose_stop_cmd_is_down(tmp_path: Path) -> None:
    """The teardown command mirrors up but ends in `down` (same project + file)."""
    run = RunCompose(runner="compose", file="docker-compose.yml")
    with patch("castle_core.deploy.shutil.which", return_value="/usr/bin/docker"):
        stop = _build_stop_cmd("supabase", run, tmp_path)
    assert stop == [
        "/usr/bin/docker",
        "compose",
        "-p",
        "castle-supabase",
        "-f",
        str(tmp_path / "docker-compose.yml"),
        "down",
    ]


def test_non_compose_runner_has_no_stop_cmd(tmp_path: Path) -> None:
    run = RunPython(runner="python", program="svc")
    assert _build_stop_cmd("svc", run, tmp_path) == []
