"""Tests for systemd unit generation."""

from __future__ import annotations

from pathlib import Path

from castle_core.generators.systemd import (
    generate_timer,
    generate_unit_from_deployed,
    secret_env_path,
    unit_env_file,
    unit_name,
)
from castle_core.registry import Deployment


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
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={"TEST_SVC_PORT": "19000"},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Description=Castle: Test service" in unit

    def test_no_working_directory(self) -> None:
        """Unit file has no WorkingDirectory (source/runtime separation)."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "WorkingDirectory" not in unit

    def test_contains_environment(self) -> None:
        """Unit file has environment variables from deployed config."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={"TEST_SVC_DATA_DIR": "/home/user/.castle/data/test-svc"},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Environment=TEST_SVC_DATA_DIR=/home/user/.castle/data/test-svc" in unit

    def test_default_path_emitted_when_absent(self) -> None:
        """Castle supplies a default PATH when the service doesn't pin one."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert 'Environment="PATH=' in unit
        assert "/usr/local/bin:/usr/bin:/bin" in unit

    def test_path_prepend_precedes_default(self) -> None:
        """A resolved toolchain dir (e.g. pinned node bin) leads the default PATH."""
        deployed = Deployment(
            manager="systemd", launcher="node",
            run_cmd=["node", "server.js"],
            env={},
            path_prepend=["/home/user/.nvm/versions/node/v24.14.1/bin"],
            description="Node service",
        )
        unit = generate_unit_from_deployed("node-svc", deployed)
        path_line = next(ln for ln in unit.splitlines() if "PATH=" in ln)
        assert "/home/user/.nvm/versions/node/v24.14.1/bin:" in path_line
        assert path_line.index("v24.14.1") < path_line.index("/usr/bin")

    def test_explicit_path_overrides_path_prepend(self) -> None:
        """An explicit PATH is a full override — path_prepend is ignored too."""
        deployed = Deployment(
            manager="systemd", launcher="node",
            run_cmd=["node", "server.js"],
            env={"PATH": "/opt/node/bin:/usr/bin:/bin"},
            path_prepend=["/home/user/.nvm/versions/node/v24.14.1/bin"],
            description="Node service",
        )
        unit = generate_unit_from_deployed("node-svc", deployed)
        assert "v24.14.1" not in unit
        assert unit.count("PATH=") == 1

    def test_explicit_path_overrides_default(self) -> None:
        """A PATH pinned in defaults.env wins — Castle does not append its own,
        which would clobber it under systemd's last-assignment-wins rule."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={"PATH": "/opt/node/bin:/usr/bin:/bin"},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Environment=PATH=/opt/node/bin:/usr/bin:/bin" in unit
        assert unit.count("PATH=") == 1  # exactly one PATH line, the explicit one

    def test_contains_restart_policy(self) -> None:
        """Unit file has restart configuration."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "Restart=on-failure" in unit

    def test_exec_start_from_run_cmd(self) -> None:
        """Unit file ExecStart uses resolved run_cmd."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "test-svc"],
            env={},
            description="Test service",
        )
        unit = generate_unit_from_deployed("test-svc", deployed)
        assert "ExecStart=/home/user/.local/bin/uv run test-svc" in unit

    def test_basic_service(self) -> None:
        """Generate a unit from a deployed component."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "my-svc"],
            env={
                "MY_SVC_PORT": "9001",
                "MY_SVC_DATA_DIR": "/home/user/.castle/data/my-svc",
            },
            description="My service",
        )
        unit = generate_unit_from_deployed("my-svc", deployed)
        assert "Description=Castle: My service" in unit
        assert "ExecStart=/home/user/.local/bin/uv run my-svc" in unit
        assert "Environment=MY_SVC_PORT=9001" in unit
        assert "Environment=MY_SVC_DATA_DIR=/home/user/.castle/data/my-svc" in unit
        assert "WorkingDirectory" not in unit
        assert "Restart=on-failure" in unit

    def test_scheduled_job(self) -> None:
        """Scheduled component generates oneshot unit."""
        deployed = Deployment(
            manager="systemd", launcher="command",
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
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/home/user/.local/bin/uv", "run", "my-svc"],
            env={"DATA_DIR": "/home/user/.castle/data/my-svc"},
            description="Test",
        )
        unit = generate_unit_from_deployed("my-svc", deployed)
        assert "/data/repos/" not in unit

    def test_exec_stop_emitted_for_compose(self) -> None:
        """A compose deployment's stop_cmd becomes ExecStop= (clean teardown)."""
        deployed = Deployment(
            manager="systemd", launcher="compose",
            run_cmd=["/usr/bin/docker", "compose", "-p", "castle-x", "-f", "c.yml", "up"],
            stop_cmd=["/usr/bin/docker", "compose", "-p", "castle-x", "-f", "c.yml", "down"],
            description="Stack",
        )
        unit = generate_unit_from_deployed("x", deployed)
        assert "ExecStop=/usr/bin/docker compose -p castle-x -f c.yml down" in unit

    def test_no_exec_stop_without_stop_cmd(self) -> None:
        """Runners without a stop_cmd rely on SIGTERM — no ExecStop line."""
        deployed = Deployment(
            manager="systemd", launcher="python", run_cmd=["/uv", "run", "x"], description="X"
        )
        unit = generate_unit_from_deployed("x", deployed)
        assert "ExecStop=" not in unit


class TestSecretEnvFile:
    """Secrets are referenced via EnvironmentFile=, never inlined."""

    def test_environment_file_added_for_simple_unit(self) -> None:
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/uv", "run", "my-svc"],
            env={"PORT": "9001"},
            secret_env_keys=["API_KEY"],
        )
        path = Path("/home/u/.castle/secrets/env/castle-my-svc.service.env")
        unit = generate_unit_from_deployed("my-svc", deployed, env_file=path)
        assert f"EnvironmentFile={path}" in unit
        # fail-loud: no '-' prefix
        assert f"EnvironmentFile=-{path}" not in unit

    def test_environment_file_added_for_oneshot_job(self) -> None:
        deployed = Deployment(
            manager="systemd", launcher="command",
            run_cmd=["/bin/job"],
            env={},
            schedule="0 2 * * *",
            secret_env_keys=["TOKEN"],
        )
        path = Path("/home/u/.castle/secrets/env/castle-my-job.service.env")
        unit = generate_unit_from_deployed("my-job", deployed, env_file=path)
        assert "Type=oneshot" in unit
        assert f"EnvironmentFile={path}" in unit

    def test_no_environment_file_when_none(self) -> None:
        deployed = Deployment(manager="systemd", launcher="python", run_cmd=["/uv", "run", "x"], env={})
        unit = generate_unit_from_deployed("x", deployed, env_file=None)
        assert "EnvironmentFile" not in unit

    def test_secret_values_never_in_unit(self) -> None:
        """The unit references the file path; resolved secret values never appear."""
        deployed = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["/uv", "run", "x"],
            env={"PORT": "9001"},
            secret_env_keys=["API_KEY"],
        )
        path = secret_env_path("x")
        unit = generate_unit_from_deployed("x", deployed, env_file=path)
        assert "sk-secret" not in unit  # value is in the file, not the unit


class TestUnitEnvFile:
    """unit_env_file decides which runners get an EnvironmentFile= path."""

    def test_none_without_secrets(self) -> None:
        d = Deployment(manager="systemd", launcher="python", run_cmd=[], env={}, secret_env_keys=[])
        assert unit_env_file(d, "x") is None

    def test_path_for_python_with_secrets(self) -> None:
        d = Deployment(manager="systemd", launcher="python", run_cmd=[], env={}, secret_env_keys=["K"])
        assert unit_env_file(d, "x") == secret_env_path("x")

    def test_none_for_container(self) -> None:
        """Containers load secrets via docker --env-file, not systemd."""
        d = Deployment(manager="systemd", launcher="container", run_cmd=[], env={}, secret_env_keys=["K"])
        assert unit_env_file(d, "x") is None


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
