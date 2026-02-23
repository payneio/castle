"""Tests for systemd unit generation."""

from __future__ import annotations

from pathlib import Path

from castle_core.config import load_config
from castle_core.generators.systemd import generate_unit, unit_name


class TestUnitName:
    """Tests for systemd unit naming."""

    def test_unit_name_format(self) -> None:
        """Unit names follow castle-<name>.service pattern."""
        assert unit_name("central-context") == "castle-central-context.service"
        assert unit_name("my-svc") == "castle-my-svc.service"


class TestUnitGeneration:
    """Tests for systemd unit file generation."""

    def test_contains_description(self, castle_root: Path) -> None:
        """Unit file has service description."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert "Description=Castle: Test service" in unit

    def test_contains_working_dir(self, castle_root: Path) -> None:
        """Unit file has correct working directory."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert f"WorkingDirectory={castle_root / 'test-svc'}" in unit

    def test_contains_environment(self, castle_root: Path) -> None:
        """Unit file has environment variables."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        expected_data_dir = str(castle_root / "data" / "test-svc")
        assert f"Environment=TEST_SVC_DATA_DIR={expected_data_dir}" in unit

    def test_contains_restart_policy(self, castle_root: Path) -> None:
        """Unit file has restart configuration."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert "Restart=on-failure" in unit

    def test_uses_uv_run(self, castle_root: Path) -> None:
        """Unit file ExecStart uses uv run for python_uv_tool."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert "run test-svc" in unit
