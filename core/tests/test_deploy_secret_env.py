"""Tests for the generated secret env file and its registry visibility."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

import castle_core.deploy as deploy
from castle_core.registry import (
    Deployment,
    NodeConfig,
    NodeRegistry,
    load_registry,
    save_registry,
)


@pytest.fixture
def secret_env_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the secret-env file location into a temp dir."""
    d = tmp_path / "secrets" / "env"
    monkeypatch.setattr(deploy, "SECRET_ENV_DIR", d)
    monkeypatch.setattr(
        deploy, "secret_env_path", lambda name: d / f"castle-{name}.service.env"
    )
    return d


class TestWriteSecretEnvFile:
    def test_writes_mode_0600_in_0700_dir(self, secret_env_dir: Path) -> None:
        path = deploy._write_secret_env_file("svc", {"API_KEY": "sk-123"})
        assert path is not None and path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(secret_env_dir.stat().st_mode) == 0o700

    def test_content_format(self, secret_env_dir: Path) -> None:
        path = deploy._write_secret_env_file(
            "svc", {"A": "1", "NEO4J_AUTH": "neo4j/pw"}
        )
        assert path is not None
        assert path.read_text() == "A=1\nNEO4J_AUTH=neo4j/pw\n"

    def test_empty_unlinks_and_returns_none(self, secret_env_dir: Path) -> None:
        path = deploy.secret_env_path("svc")
        secret_env_dir.mkdir(parents=True)
        path.write_text("STALE=1\n")
        result = deploy._write_secret_env_file("svc", {})
        assert result is None
        assert not path.exists()

    def test_rewrite_truncates_and_fixes_mode(self, secret_env_dir: Path) -> None:
        deploy._write_secret_env_file("svc", {"A": "old", "B": "x"})
        path = deploy._write_secret_env_file("svc", {"A": "new"})
        assert path is not None
        assert path.read_text() == "A=new\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestRegistrySecretKeys:
    def test_round_trip_persists_keys_only(self, tmp_path: Path) -> None:
        reg_path = tmp_path / "registry.yaml"
        registry = NodeRegistry(node=NodeConfig(hostname="h"))
        registry.put(
            Deployment(
                manager="systemd", launcher="container",
                run_cmd=["docker", "run"],
                env={"PORT": "9001"},
                secret_env_keys=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
                managed=True,
                name="svc",
            )
        )
        save_registry(registry, reg_path)

        text = reg_path.read_text()
        assert "ANTHROPIC_API_KEY" in text  # names are fine
        assert "sk-ant" not in text  # but no values ever

        loaded = load_registry(reg_path)
        svc = loaded.get("service", "svc")
        assert svc.secret_env_keys == ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
        assert svc.env == {"PORT": "9001"}
