"""Tests for units: expansion."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from castle_core.config import load_config, save_config
from castle_core.manifest import UnitKind, UnitSpec


@pytest.fixture
def units_root(tmp_path: Path) -> Path:
    """Castle root with a units: section."""
    config = {
        "gateway": {"port": 18000},
        "units": {
            "my-svc": {
                "kind": "service",
                "stack": "python-fastapi",
                "description": "Test service",
                "source": "code/my-svc",
                "port": 9050,
                "path_prefix": "/my-svc",
            },
            "my-tool": {
                "kind": "tool",
                "stack": "python-cli",
                "description": "Test tool",
                "source": "code/my-tool",
                "system_dependencies": ["pandoc"],
            },
            "my-site": {
                "kind": "site",
                "stack": "react-vite",
                "description": "Test frontend",
                "source": "code/my-site",
                "build": {
                    "commands": [["pnpm", "build"]],
                    "outputs": ["dist/"],
                },
            },
            "my-job": {
                "kind": "job",
                "stack": "python-cli",
                "description": "Test job",
                "source": "code/my-job",
                "schedule": "0 2 * * *",
                "argv": ["my-job", "run"],
                "env": {"DATA_DIR": "/tmp/data"},
            },
        },
    }
    (tmp_path / "castle.yaml").write_text(
        yaml.dump(config, default_flow_style=False)
    )
    return tmp_path


class TestUnitExpansion:

    def test_service_creates_program_and_service(self, units_root: Path) -> None:
        config = load_config(units_root)
        assert "my-svc" in config.programs
        assert "my-svc" in config.services
        prog = config.programs["my-svc"]
        assert prog.behavior == "daemon"
        assert prog.stack == "python-fastapi"
        assert prog.description == "Test service"
        svc = config.services["my-svc"]
        assert svc.run.runner == "python"
        assert svc.run.program == "my-svc"
        assert svc.expose.http.internal.port == 9050
        assert svc.expose.http.health_path == "/health"
        assert svc.proxy.caddy.path_prefix == "/my-svc"
        assert svc.manage.systemd is not None
        assert svc.program == "my-svc"

    def test_tool_creates_program_only(self, units_root: Path) -> None:
        config = load_config(units_root)
        assert "my-tool" in config.programs
        assert "my-tool" not in config.services
        assert "my-tool" not in config.jobs
        prog = config.programs["my-tool"]
        assert prog.behavior == "tool"
        assert prog.system_dependencies == ["pandoc"]

    def test_site_creates_program_with_build(self, units_root: Path) -> None:
        config = load_config(units_root)
        assert "my-site" in config.programs
        assert "my-site" not in config.services
        prog = config.programs["my-site"]
        assert prog.behavior == "frontend"
        assert prog.build is not None
        assert prog.build.outputs == ["dist/"]

    def test_job_creates_program_and_job(self, units_root: Path) -> None:
        config = load_config(units_root)
        assert "my-job" in config.programs
        assert "my-job" in config.jobs
        assert "my-job" not in config.services
        prog = config.programs["my-job"]
        assert prog.behavior == "tool"
        job = config.jobs["my-job"]
        assert job.schedule == "0 2 * * *"
        assert job.run.runner == "command"
        assert job.run.argv == ["my-job", "run"]
        assert job.defaults.env["DATA_DIR"] == "/tmp/data"
        assert job.program == "my-job"

    def test_service_without_path_prefix(self, tmp_path: Path) -> None:
        config_data = {
            "gateway": {"port": 18000},
            "units": {
                "internal-svc": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9060,
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        svc = config.services["internal-svc"]
        assert svc.proxy is None

    def test_service_with_env(self, tmp_path: Path) -> None:
        config_data = {
            "gateway": {"port": 18000},
            "units": {
                "svc-env": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9060,
                    "env": {"API_KEY": "test123"},
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        svc = config.services["svc-env"]
        assert svc.defaults.env["API_KEY"] == "test123"

    def test_service_custom_health_path(self, tmp_path: Path) -> None:
        config_data = {
            "gateway": {"port": 18000},
            "units": {
                "custom-health": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9060,
                    "health_path": "/status",
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        svc = config.services["custom-health"]
        assert svc.expose.http.health_path == "/status"

    def test_source_paths_resolved(self, units_root: Path) -> None:
        config = load_config(units_root)
        prog = config.programs["my-tool"]
        assert prog.source == str(units_root / "code" / "my-tool")

    def test_repo_source_paths_resolved(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        config_data = {
            "gateway": {"port": 18000},
            "repo": str(repo_dir),
            "units": {
                "repo-svc": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9060,
                    "source": "repo:my-api",
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        assert config.programs["repo-svc"].source == str(repo_dir / "my-api")


class TestUnitValidation:

    def test_service_requires_port(self) -> None:
        with pytest.raises(ValueError, match="requires 'port'"):
            UnitSpec(id="bad", kind=UnitKind.SERVICE, stack="python-fastapi")

    def test_job_requires_schedule(self) -> None:
        with pytest.raises(ValueError, match="requires 'schedule'"):
            UnitSpec(id="bad", kind=UnitKind.JOB, argv=["x"])

    def test_job_requires_argv(self) -> None:
        with pytest.raises(ValueError, match="requires 'argv'"):
            UnitSpec(id="bad", kind=UnitKind.JOB, schedule="0 * * * *")

    def test_tool_needs_no_port(self) -> None:
        unit = UnitSpec(id="ok", kind=UnitKind.TOOL, stack="python-cli")
        assert unit.port is None

    def test_site_needs_no_port(self) -> None:
        unit = UnitSpec(id="ok", kind=UnitKind.SITE, stack="react-vite")
        assert unit.port is None


class TestUnitConflicts:

    def test_conflict_with_existing_program(self, tmp_path: Path) -> None:
        config = {
            "gateway": {"port": 18000},
            "programs": {
                "conflict": {
                    "description": "Existing",
                    "behavior": "tool",
                },
            },
            "units": {
                "conflict": {
                    "kind": "tool",
                    "stack": "python-cli",
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config, default_flow_style=False)
        )
        with pytest.raises(ValueError, match="conflicts"):
            load_config(tmp_path)

    def test_conflict_with_existing_service(self, tmp_path: Path) -> None:
        config = {
            "gateway": {"port": 18000},
            "services": {
                "conflict": {
                    "run": {"runner": "command", "argv": ["svc"]},
                },
            },
            "units": {
                "conflict": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9999,
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config, default_flow_style=False)
        )
        with pytest.raises(ValueError, match="conflicts"):
            load_config(tmp_path)


class TestUnitCoexistence:

    def test_units_and_explicit_coexist(self, tmp_path: Path) -> None:
        config = {
            "gateway": {"port": 18000},
            "programs": {
                "manual-tool": {
                    "description": "Manual",
                    "behavior": "tool",
                },
            },
            "services": {
                "manual-svc": {
                    "run": {"runner": "command", "argv": ["svc"]},
                    "expose": {"http": {"internal": {"port": 19000}}},
                },
            },
            "units": {
                "unit-svc": {
                    "kind": "service",
                    "stack": "python-fastapi",
                    "port": 9070,
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config, default_flow_style=False)
        )
        cfg = load_config(tmp_path)
        assert "manual-tool" in cfg.programs
        assert "manual-svc" in cfg.services
        assert "unit-svc" in cfg.programs
        assert "unit-svc" in cfg.services


class TestUnitRoundTrip:

    def test_save_preserves_units_section(self, units_root: Path) -> None:
        config = load_config(units_root)
        save_config(config)
        config2 = load_config(units_root)
        assert "my-svc" in config2.programs
        assert "my-svc" in config2.services
        assert "my-tool" in config2.programs
        assert "my-job" in config2.jobs

    def test_save_does_not_duplicate_into_explicit_sections(
        self, units_root: Path
    ) -> None:
        config = load_config(units_root)
        save_config(config)
        raw = yaml.safe_load((units_root / "castle.yaml").read_text())
        # Unit entries should NOT appear in programs/services/jobs sections
        assert "my-svc" not in raw.get("programs", {})
        assert "my-svc" not in raw.get("services", {})
        assert "my-job" not in raw.get("jobs", {})
        # They should still be in units:
        assert "my-svc" in raw.get("units", {})
        assert "my-tool" in raw.get("units", {})
        assert "my-job" in raw.get("units", {})

    def test_mixed_save_separates_correctly(self, tmp_path: Path) -> None:
        config_data = {
            "gateway": {"port": 18000},
            "programs": {
                "manual-tool": {
                    "description": "Manual",
                    "behavior": "tool",
                    "source": "code/manual",
                },
            },
            "units": {
                "unit-tool": {
                    "kind": "tool",
                    "stack": "python-cli",
                    "source": "code/unit-tool",
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        save_config(config)
        raw = yaml.safe_load((tmp_path / "castle.yaml").read_text())
        # manual-tool stays in programs, unit-tool stays in units
        assert "manual-tool" in raw.get("programs", {})
        assert "unit-tool" not in raw.get("programs", {})
        assert "unit-tool" in raw.get("units", {})


class TestNoUnitsSection:

    def test_config_without_units_works(self, tmp_path: Path) -> None:
        config_data = {
            "gateway": {"port": 18000},
            "programs": {
                "some-tool": {
                    "description": "A tool",
                    "behavior": "tool",
                },
            },
        }
        (tmp_path / "castle.yaml").write_text(
            yaml.dump(config_data, default_flow_style=False)
        )
        config = load_config(tmp_path)
        assert "some-tool" in config.programs
        assert not config._unit_names
