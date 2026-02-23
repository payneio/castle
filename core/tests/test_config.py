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
from castle_core.manifest import ComponentManifest, Role


class TestLoadConfig:
    """Tests for loading castle.yaml."""

    def test_load_basic(self, castle_root: Path) -> None:
        """Load a castle.yaml."""
        config = load_config(castle_root)
        assert isinstance(config, CastleConfig)
        assert config.gateway.port == 18000
        assert "test-svc" in config.components
        assert "test-tool" in config.components

    def test_load_produces_manifests(self, castle_root: Path) -> None:
        """Components are ComponentManifest objects."""
        config = load_config(castle_root)
        assert isinstance(config.components["test-svc"], ComponentManifest)
        assert isinstance(config.components["test-tool"], ComponentManifest)

    def test_service_roles(self, castle_root: Path) -> None:
        """Service with expose.http gets SERVICE role."""
        config = load_config(castle_root)
        svc = config.components["test-svc"]
        assert Role.SERVICE in svc.roles

    def test_tool_roles(self, castle_root: Path) -> None:
        """Tool with install.path gets TOOL role."""
        config = load_config(castle_root)
        tool = config.components["test-tool"]
        assert Role.TOOL in tool.roles

    def test_service_expose(self, castle_root: Path) -> None:
        """Service has correct expose spec."""
        config = load_config(castle_root)
        svc = config.components["test-svc"]
        assert svc.expose.http.internal.port == 19000
        assert svc.expose.http.health_path == "/health"

    def test_service_proxy(self, castle_root: Path) -> None:
        """Service has correct proxy spec."""
        config = load_config(castle_root)
        svc = config.components["test-svc"]
        assert svc.proxy.caddy.path_prefix == "/test-svc"

    def test_service_run_spec(self, castle_root: Path) -> None:
        """Service has correct RunSpec."""
        config = load_config(castle_root)
        svc = config.components["test-svc"]
        assert svc.run.runner == "python_uv_tool"
        assert svc.run.tool == "test-svc"
        assert svc.run.working_dir == "test-svc"

    def test_tool_no_run(self, castle_root: Path) -> None:
        """Tool without run block has no run spec."""
        config = load_config(castle_root)
        tool = config.components["test-tool"]
        assert tool.run is None

    def test_services_property(self, castle_root: Path) -> None:
        """Services property filters to SERVICE role."""
        config = load_config(castle_root)
        assert "test-svc" in config.services
        assert "test-tool" not in config.services

    def test_tools_property(self, castle_root: Path) -> None:
        """Tools property filters to TOOL role."""
        config = load_config(castle_root)
        assert "test-tool" in config.tools
        assert "test-svc" not in config.tools

    def test_managed_property(self, castle_root: Path) -> None:
        """Managed property returns systemd-managed components."""
        config = load_config(castle_root)
        assert "test-svc" in config.managed
        assert "test-tool" not in config.managed

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

    def test_save_adds_component(self, castle_root: Path) -> None:
        """Adding a component and saving persists it."""
        config = load_config(castle_root)
        config.components["new-lib"] = ComponentManifest(
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
        assert "test-svc" in config2.managed


class TestResolveEnvVars:
    """Tests for environment variable resolution."""

    def test_no_vars(self) -> None:
        """Plain values pass through unchanged."""
        manifest = ComponentManifest(id="test")
        env = {"MY_VAR": "plain_value"}
        resolved = resolve_env_vars(env, manifest)
        assert resolved["MY_VAR"] == "plain_value"

    def test_unrecognized_vars_preserved(self) -> None:
        """Non-secret ${} references pass through unchanged."""
        manifest = ComponentManifest(id="test")
        env = {"MY_VAR": "${unknown_var}"}
        resolved = resolve_env_vars(env, manifest)
        assert resolved["MY_VAR"] == "${unknown_var}"

    def test_resolve_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${secret:NAME} resolves from secrets directory."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "API_KEY").write_text("my-secret-key\n")
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        manifest = ComponentManifest(id="test")
        env = {"API_KEY": "${secret:API_KEY}"}
        resolved = resolve_env_vars(env, manifest)
        assert resolved["API_KEY"] == "my-secret-key"

    def test_resolve_missing_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing secret returns placeholder."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        manifest = ComponentManifest(id="test")
        env = {"API_KEY": "${secret:NONEXISTENT}"}
        resolved = resolve_env_vars(env, manifest)
        assert resolved["API_KEY"] == "<MISSING_SECRET:NONEXISTENT>"
