"""Test fixtures for castle-api."""

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import castle_api.config as api_config
from castle_api.main import app
from castle_core.registry import (
    DeployedComponent,
    NodeConfig,
    NodeRegistry,
    save_registry,
)


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with castle.yaml."""
    castle_yaml = tmp_path / "castle.yaml"
    config = {
        "gateway": {"port": 9000},
        "programs": {
            "test-tool": {
                "description": "Test tool",
                "source": "test-tool",
                "behavior": "tool",
                "system_dependencies": ["pandoc"],
            },
            "test-tool-2": {
                "description": "Another test tool",
                "source": "test-tool-2",
                "behavior": "tool",
                "version": "2.0.0",
            },
        },
        "services": {
            "test-svc": {
                "component": "test-svc-comp",
                "description": "Test service",
                "run": {
                    "runner": "python",
                    "program": "test-svc",
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
    castle_yaml.write_text(yaml.dump(config, default_flow_style=False))
    yield tmp_path


@pytest.fixture
def registry_path(tmp_path: Path, castle_root: Path) -> Generator[Path, None, None]:
    """Create a temporary registry.yaml and patch the module to use it."""
    reg_path = tmp_path / "registry.yaml"
    registry = NodeRegistry(
        node=NodeConfig(
            hostname="test-node",
            castle_root=str(castle_root),
            gateway_port=9000,
        ),
        deployed={
            "test-svc": DeployedComponent(
                runner="python",
                run_cmd=["uv", "run", "test-svc"],
                env={
                    "TEST_SVC_PORT": "19000",
                    "TEST_SVC_DATA_DIR": "/data/castle/test-svc",
                },
                description="Test service",
                behavior="daemon",
                port=19000,
                health_path="/health",
                proxy_path="/test-svc",
                managed=True,
            ),
        },
    )
    save_registry(registry, reg_path)

    # Patch the registry path and helper functions
    import castle_core.registry as reg_mod

    original_path = reg_mod.REGISTRY_PATH
    reg_mod.REGISTRY_PATH = reg_path

    original_get_registry = api_config.get_registry
    original_get_castle_root = api_config.get_castle_root

    def _get_registry() -> NodeRegistry:
        from castle_core.registry import load_registry

        return load_registry(reg_path)

    def _get_castle_root() -> Path | None:
        return castle_root

    api_config.get_registry = _get_registry
    api_config.get_castle_root = _get_castle_root

    yield reg_path

    reg_mod.REGISTRY_PATH = original_path
    api_config.get_registry = original_get_registry
    api_config.get_castle_root = original_get_castle_root


@pytest.fixture
def client(registry_path: Path) -> Generator[TestClient, None, None]:
    """Create a test client with temporary registry."""
    with TestClient(app) as client:
        yield client
