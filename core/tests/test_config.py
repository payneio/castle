"""Tests for castle configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from castle_core.config import (
    CastleConfig,
    load_config,
    resolve_env_vars,
    save_config,
)
from castle_core.manifest import ComponentSpec, JobSpec, ServiceSpec


class TestLoadConfig:
    """Tests for loading castle.yaml."""

    def test_load_basic(self, castle_root: Path) -> None:
        """Load a castle.yaml with three sections."""
        config = load_config(castle_root)
        assert isinstance(config, CastleConfig)
        assert config.gateway.port == 18000
        assert "test-tool" in config.components
        assert "test-svc" in config.services
        assert "test-job" in config.jobs

    def test_load_produces_typed_specs(self, castle_root: Path) -> None:
        """Each section produces the correct spec type."""
        config = load_config(castle_root)
        assert isinstance(config.components["test-tool"], ComponentSpec)
        assert isinstance(config.services["test-svc"], ServiceSpec)
        assert isinstance(config.jobs["test-job"], JobSpec)

    def test_service_expose(self, castle_root: Path) -> None:
        """Service has correct expose spec."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.expose.http.internal.port == 19000
        assert svc.expose.http.health_path == "/health"

    def test_service_proxy(self, castle_root: Path) -> None:
        """Service has correct proxy spec."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.proxy.caddy.path_prefix == "/test-svc"

    def test_service_run_spec(self, castle_root: Path) -> None:
        """Service has correct RunSpec."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.run.runner == "python"
        assert svc.run.tool == "test-svc"

    def test_service_component_ref(self, castle_root: Path) -> None:
        """Service references a component."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.component == "test-svc-comp"

    def test_job_schedule(self, castle_root: Path) -> None:
        """Job has correct schedule."""
        config = load_config(castle_root)
        job = config.jobs["test-job"]
        assert job.schedule == "0 2 * * *"

    def test_tools_property(self, castle_root: Path) -> None:
        """Tools property filters to components with install.path or tool."""
        config = load_config(castle_root)
        assert "test-tool" in config.tools

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        """Missing castle.yaml raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path)


class TestSaveConfig:
    """Tests for saving castle.yaml."""

    def test_round_trip(self, castle_root: Path) -> None:
        """Load and save should produce equivalent config."""
        config = load_config(castle_root)
        save_config(config)
        config2 = load_config(castle_root)

        assert config2.gateway.port == config.gateway.port
        assert set(config2.components.keys()) == set(config.components.keys())
        assert set(config2.services.keys()) == set(config.services.keys())
        assert set(config2.jobs.keys()) == set(config.jobs.keys())

    def test_save_adds_component(self, castle_root: Path) -> None:
        """Adding a component and saving persists it."""
        config = load_config(castle_root)
        config.components["new-lib"] = ComponentSpec(
            id="new-lib", description="A new library"
        )
        save_config(config)

        config2 = load_config(castle_root)
        assert "new-lib" in config2.components
        assert config2.components["new-lib"].description == "A new library"

    def test_preserves_manage_systemd(self, castle_root: Path) -> None:
        """Roundtrip preserves manage.systemd even with all defaults."""
        config = load_config(castle_root)
        save_config(config)
        config2 = load_config(castle_root)
        svc = config2.services["test-svc"]
        assert svc.manage is not None
        assert svc.manage.systemd is not None


class TestResolveEnvVars:
    """Tests for environment variable resolution."""

    def test_no_vars(self) -> None:
        """Plain values pass through unchanged."""
        env = {"MY_VAR": "plain_value"}
        resolved = resolve_env_vars(env)
        assert resolved["MY_VAR"] == "plain_value"

    def test_unrecognized_vars_preserved(self) -> None:
        """Non-secret ${} references pass through unchanged."""
        env = {"MY_VAR": "${unknown_var}"}
        resolved = resolve_env_vars(env)
        assert resolved["MY_VAR"] == "${unknown_var}"

    def test_resolve_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${secret:NAME} resolves from secrets directory."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "API_KEY").write_text("my-secret-key\n")
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        env = {"API_KEY": "${secret:API_KEY}"}
        resolved = resolve_env_vars(env)
        assert resolved["API_KEY"] == "my-secret-key"

    def test_resolve_missing_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing secret returns placeholder."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        env = {"API_KEY": "${secret:NONEXISTENT}"}
        resolved = resolve_env_vars(env)
        assert resolved["API_KEY"] == "<MISSING_SECRET:NONEXISTENT>"
