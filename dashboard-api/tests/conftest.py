"""Test fixtures for dashboard-api."""

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard_api.config import settings
from dashboard_api.main import app


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with castle.yaml."""
    castle_yaml = tmp_path / "castle.yaml"
    config = {
        "gateway": {"port": 9000},
        "components": {
            "test-svc": {
                "description": "Test service",
                "run": {
                    "runner": "python_uv_tool",
                    "tool": "test-svc",
                    "cwd": "test-svc",
                },
                "expose": {
                    "http": {
                        "internal": {"port": 19000},
                        "health_path": "/health",
                    }
                },
                "proxy": {"caddy": {"path_prefix": "/test-svc"}},
                "manage": {"systemd": {}},
            },
            "test-tool": {
                "description": "Test tool",
                "install": {"path": {"alias": "test-tool"}},
            },
        },
    }
    castle_yaml.write_text(yaml.dump(config, default_flow_style=False))

    original = settings.castle_root
    settings.castle_root = tmp_path
    yield tmp_path
    settings.castle_root = original


@pytest.fixture
def client(castle_root: Path) -> Generator[TestClient, None, None]:
    """Create a test client pointing to temporary castle root."""
    with TestClient(app) as client:
        yield client
