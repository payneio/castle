"""Shared fixtures for castle CLI tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml


def _write_castle_config(root: Path, config: dict) -> None:
    """Scatter a nested castle config dict into the directory-per-resource layout."""
    globals_data = {k: v for k, v in config.items() if k in ("gateway", "repo")}
    (root / "castle.yaml").write_text(yaml.dump(globals_data, default_flow_style=False))
    for section in ("programs", "services", "jobs"):
        entries = config.get(section) or {}
        if not entries:
            continue
        section_dir = root / section
        section_dir.mkdir(parents=True, exist_ok=True)
        for name, spec in entries.items():
            (section_dir / f"{name}.yaml").write_text(yaml.dump(spec, default_flow_style=False))


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with directory-per-resource config."""
    config = {
        "gateway": {"port": 18000},
        "programs": {
            "test-tool": {
                "description": "Test tool",
                "behavior": "tool",
            },
            "test-daemon": {
                "description": "Test daemon program",
                "behavior": "daemon",
            },
        },
        "services": {
            "test-svc": {
                "program": "test-svc-comp",
                "description": "Test service",
                "run": {
                    "runner": "python",
                    "program": "test-svc",
                },
                "defaults": {
                    "env": {"TEST_SVC_DATA_DIR": str(tmp_path / "data" / "test-svc")},
                },
                "expose": {
                    "http": {
                        "internal": {"port": 19000},
                        "health_path": "/health",
                    }
                },
                "proxy": True,
                "manage": {
                    "systemd": {},
                },
            },
        },
        "jobs": {
            "test-job": {
                "description": "Test job",
                "run": {
                    "runner": "command",
                    "argv": ["test-job"],
                },
                "schedule": "0 2 * * *",
            },
        },
    }
    _write_castle_config(tmp_path, config)

    # Create project directories
    svc_dir = tmp_path / "test-svc"
    svc_dir.mkdir()
    (svc_dir / "pyproject.toml").write_text("[project]\nname = 'test-svc'\n")

    tool_dir = tmp_path / "test-tool"
    tool_dir.mkdir()

    yield tmp_path


@pytest.fixture
def castle_home(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary ~/.castle directory."""
    home = tmp_path / ".castle"
    home.mkdir()
    (home / "generated").mkdir()
    (home / "secrets").mkdir()
    yield home
