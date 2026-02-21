"""Shared fixtures for castle CLI tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with castle.yaml."""
    castle_yaml = tmp_path / "castle.yaml"
    config = {
        "gateway": {"port": 18000},
        "components": {
            "test-svc": {
                "description": "Test service",
                "run": {
                    "runner": "python_uv_tool",
                    "tool": "test-svc",
                    "cwd": "test-svc",
                    "env": {"TEST_SVC_DATA_DIR": str(tmp_path / "data" / "test-svc")},
                },
                "expose": {
                    "http": {
                        "internal": {"port": 19000},
                        "health_path": "/health",
                    }
                },
                "proxy": {
                    "caddy": {"path_prefix": "/test-svc"},
                },
                "manage": {
                    "systemd": {},
                },
            },
            "test-tool": {
                "description": "Test tool",
                "install": {
                    "path": {"alias": "test-tool"},
                },
            },
        },
    }
    castle_yaml.write_text(yaml.dump(config, default_flow_style=False))

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
