"""Tests for systemd unit generation."""

from __future__ import annotations

from pathlib import Path

from castle_core.config import load_config
from castle_core.generators.systemd import (
    generate_unit,
    generate_unit_from_deployed,
    unit_name,
)
from castle_core.registry import DeployedComponent


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

    def test_no_working_directory(self, castle_root: Path) -> None:
        """Unit file has no WorkingDirectory (source/runtime separation)."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert "WorkingDirectory" not in unit

    def test_contains_environment(self, castle_root: Path) -> None:
        """Unit file has environment variables from defaults.env."""
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
        """Unit file ExecStart uses uv run for python runner."""
        config = load_config(castle_root)
        manifest = config.components["test-svc"]
        unit = generate_unit(config, "test-svc", manifest)
        assert "run test-svc" in unit


class TestUnitFromDeployed:
    """Tests for registry-based systemd unit generation."""

    def test_basic_service(self) -> None:
        """Generate a unit from a deployed component."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "my-svc"],
            env={"MY_SVC_PORT": "9001", "MY_SVC_DATA_DIR": "/data/castle/my-svc"},
            description="My service",
        )
        unit = generate_unit_from_deployed("my-svc", deployed)
        assert "Description=Castle: My service" in unit
        assert "ExecStart=/home/user/.local/bin/uv run my-svc" in unit
        assert "Environment=MY_SVC_PORT=9001" in unit
        assert "Environment=MY_SVC_DATA_DIR=/data/castle/my-svc" in unit
        assert "WorkingDirectory" not in unit
        assert "Restart=on-failure" in unit

    def test_scheduled_job(self) -> None:
        """Scheduled component generates oneshot unit."""
        deployed = DeployedComponent(
            runner="command",
            run_cmd=["/home/user/.local/bin/my-job"],
            env={},
            description="Nightly job",
            schedule="0 2 * * *",
        )
        unit = generate_unit_from_deployed("my-job", deployed)
        assert "Type=oneshot" in unit
        assert "Restart=" not in unit

    def test_no_repo_paths(self) -> None:
        """Generated units must not reference repo paths."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "my-svc"],
            env={"DATA_DIR": "/data/castle/my-svc"},
            description="Test",
        )
        unit = generate_unit_from_deployed("my-svc", deployed)
        assert "/data/repos/" not in unit
