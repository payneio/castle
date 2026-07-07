"""Test fixtures for castle-api."""

import socket
import subprocess
import time
import urllib.request
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import castle_api.config as api_config
from castle_api.main import app
from castle_core.registry import (
    Deployment,
    NodeConfig,
    NodeRegistry,
    save_registry,
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _docker_available() -> bool:
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        ).returncode == 0
    except Exception:
        return False


@pytest.fixture
def nats_url() -> Generator[str, None, None]:
    """A throwaway NATS+JetStream broker in docker (fresh per test for clean
    buckets). Skips if docker is unavailable."""
    if not _docker_available():
        pytest.skip("docker unavailable — skipping NATS integration tests")
    cport, mport = _free_port(), _free_port()
    name = f"castle-test-nats-{cport}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "-p", f"{cport}:4222", "-p", f"{mport}:8222", "nats:2", "-js", "-m", "8222"],
        check=True, capture_output=True,
    )
    try:
        for _ in range(50):  # wait for readiness
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{mport}/healthz", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        yield f"nats://127.0.0.1:{cport}"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


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
            (section_dir / f"{name}.yaml").write_text(
                yaml.dump(spec, default_flow_style=False)
            )


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with directory-per-resource config."""
    config = {
        "gateway": {"port": 9000},
        "programs": {
            "test-tool": {
                "description": "Test tool",
                "source": "test-tool",
                "system_dependencies": ["pandoc"],
            },
            "test-tool-2": {
                "description": "Another test tool",
                "source": "test-tool-2",
                "version": "2.0.0",
            },
            "wired-in": {
                "description": "Adopted repo, no stack",
                "source": "wired-in",
                "repo": "https://github.com/someone/wired-in.git",
                "commands": {
                    "lint": [["make", "lint"]],
                    "test": [["make", "test"]],
                    "run": [["./bin/wired-in"]],
                },
            },
        },
        "services": {
            # Path deployments — behavior "tool" derives from the `path` runner
            # (behavior is derived from deployments, never stored).
            "test-tool": {"program": "test-tool", "run": {"runner": "path"}},
            "test-tool-2": {"program": "test-tool-2", "run": {"runner": "path"}},
            "wired-in": {"program": "wired-in", "run": {"runner": "path"}},
            "test-svc": {
                "program": "test-svc-comp",
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
                "proxy": True,
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
    _write_castle_config(tmp_path, config)
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
            "test-svc": Deployment(
                manager="systemd",
                launcher="python",
                run_cmd=["uv", "run", "test-svc"],
                env={
                    "TEST_SVC_PORT": "19000",
                    "TEST_SVC_DATA_DIR": "/home/user/.castle/data/test-svc",
                },
                description="Test service",
                kind="service",
                port=19000,
                health_path="/health",
                subdomain="test-svc",
                managed=True,
            ),
            # A deployed tool (path) — must NOT leak into the /services list.
            "test-tool": Deployment(
                manager="path",
                run_cmd=[],
                description="Test tool",
                kind="tool",
            ),
        },
    )
    save_registry(registry, reg_path)

    # Patch the registry path and helper functions
    import castle_core.registry as reg_mod
    import castle_api.routes as routes_mod
    import castle_api.services as services_mod
    import castle_api.nodes as nodes_mod
    import castle_api.stream as stream_mod
    import castle_api.config_editor as config_editor_mod

    original_path = reg_mod.REGISTRY_PATH
    reg_mod.REGISTRY_PATH = reg_path

    def _get_registry() -> NodeRegistry:
        from castle_core.registry import load_registry

        return load_registry(reg_path)

    def _get_castle_root() -> Path | None:
        return castle_root

    # Save originals and patch everywhere these are imported
    originals = {
        "api_config.get_registry": api_config.get_registry,
        "api_config.get_castle_root": api_config.get_castle_root,
        "routes.get_registry": routes_mod.get_registry,
        "routes.get_castle_root": routes_mod.get_castle_root,
        "services.get_registry": services_mod.get_registry,
        "services.get_castle_root": services_mod.get_castle_root,
        "nodes.get_registry": nodes_mod.get_registry,
        "stream.get_registry": stream_mod.get_registry,
        "config_editor.get_castle_root": config_editor_mod.get_castle_root,
    }

    for mod in [
        api_config,
        routes_mod,
        services_mod,
        nodes_mod,
        stream_mod,
        config_editor_mod,
    ]:
        if hasattr(mod, "get_registry"):
            mod.get_registry = _get_registry
        if hasattr(mod, "get_castle_root"):
            mod.get_castle_root = _get_castle_root

    yield reg_path

    reg_mod.REGISTRY_PATH = original_path
    api_config.get_registry = originals["api_config.get_registry"]
    api_config.get_castle_root = originals["api_config.get_castle_root"]
    routes_mod.get_registry = originals["routes.get_registry"]
    routes_mod.get_castle_root = originals["routes.get_castle_root"]
    services_mod.get_registry = originals["services.get_registry"]
    services_mod.get_castle_root = originals["services.get_castle_root"]
    nodes_mod.get_registry = originals["nodes.get_registry"]
    stream_mod.get_registry = originals["stream.get_registry"]
    config_editor_mod.get_castle_root = originals["config_editor.get_castle_root"]


@pytest.fixture
def client(registry_path: Path) -> Generator[TestClient, None, None]:
    """Create a test client with temporary registry."""
    with TestClient(app) as client:
        yield client
