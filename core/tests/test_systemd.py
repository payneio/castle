"""Tests for systemd unit generation."""

from __future__ import annotations

from castle_core.generators.systemd import (
    generate_timer,
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


class TestUnitFromDeployed:
    """Tests for registry-based systemd unit generation."""

    def test_contains_description(self) -> None:
        """Unit file has service description."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={"TEST_SVC_PORT": "19000"},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Description=Castle: Test service" in unit

    def test_no_working_directory(self) -> None:
        """Unit file has no WorkingDirectory (source/runtime separation)."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "WorkingDirectory" not in unit

    def test_contains_environment(self) -> None:
        """Unit file has environment variables from deployed config."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={"TEST_SVC_DATA_DIR": "/data/castle/test-svc"},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Environment=TEST_SVC_DATA_DIR=/data/castle/test-svc" in unit

    def test_contains_restart_policy(self) -> None:
        """Unit file has restart configuration."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Restart=on-failure" in unit

    def test_exec_start_from_run_cmd(self) -> None:
        """Unit file ExecStart uses resolved run_cmd."""
        deployed = DeployedComponent(
            runner="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "ExecStart=/home/user/.local/bin/uv run test-svc" in unit

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


class TestGenerateTimer:
    """Tests for timer generation from schedule strings."""

    def test_daily_timer(self) -> None:
        """Daily cron produces OnCalendar timer."""
        timer = generate_timer("my-job", schedule="0 2 * * *", description="Nightly")
        assert "Description=Castle timer: Nightly" in timer
        assert "OnCalendar=*-*-* 02:00:00" in timer
        assert "WantedBy=timers.target" in timer

    def test_interval_timer(self) -> None:
        """*/N minute cron produces OnUnitActiveSec timer."""
        timer = generate_timer("sync", schedule="*/5 * * * *")
        assert "OnUnitActiveSec=300s" in timer
        assert "OnBootSec=60" in timer

    def test_fallback_description(self) -> None:
        """Timer uses name when no description given."""
        timer = generate_timer("my-job", schedule="0 0 * * *")
        assert "Description=Castle timer: my-job" in timer
