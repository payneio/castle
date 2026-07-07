"""Shared fixtures for castle CLI tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml


def _modernize_deployment(spec: dict) -> dict:
    """Translate a test's terse legacy deployment dict to the current
    manager-discriminated shape (production dropped this read-compat post-migration).
    ``proxy``/``public`` → ``reach``; ``run.runner`` → ``manager`` (+ ``run.launcher``)."""
    d = dict(spec)
    proxy = bool(d.pop("proxy", False))
    public = bool(d.pop("public", False))
    if "reach" not in d:
        if public:
            d["reach"] = "public"
        elif proxy:
            d["reach"] = "internal"
    if "manager" not in d:
        run = dict(d.pop("run", None) or {})
        runner = run.get("runner")
        if runner == "static":
            d["manager"] = "caddy"
            if run.get("root"):
                d["root"] = run["root"]
        elif runner == "path":
            d["manager"] = "path"
        elif runner == "remote":
            d["manager"] = "none"
            for k in ("base_url", "health_url"):
                if run.get(k):
                    d[k] = run[k]
        else:
            launch = {k: v for k, v in run.items() if k != "runner"}
            launch["launcher"] = runner
            d["manager"] = "systemd"
            d["run"] = launch
    return d


def _store_for(spec: dict) -> str:
    if spec.get("schedule"):
        return "jobs"
    return {"systemd": "services", "caddy": "statics", "path": "tools", "none": "references"}[
        spec["manager"]
    ]


def _write_castle_config(root: Path, config: dict) -> None:
    """Scatter a nested castle config dict into the on-disk layout: castle.yaml globals,
    programs/<name>.yaml, and deployments/<kind>/<name>.yaml (fields modernized)."""
    globals_data = {k: v for k, v in config.items() if k in ("gateway", "repo")}
    (root / "castle.yaml").write_text(yaml.dump(globals_data, default_flow_style=False))
    programs = config.get("programs") or {}
    if programs:
        (root / "programs").mkdir(parents=True, exist_ok=True)
        for name, spec in programs.items():
            (root / "programs" / f"{name}.yaml").write_text(yaml.dump(spec, default_flow_style=False))
    for section in ("services", "jobs", "deployments"):
        for name, spec in (config.get(section) or {}).items():
            modern = _modernize_deployment(spec)
            store_dir = root / "deployments" / _store_for(modern)
            store_dir.mkdir(parents=True, exist_ok=True)
            (store_dir / f"{name}.yaml").write_text(yaml.dump(modern, default_flow_style=False))


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with directory-per-resource config."""
    config = {
        "gateway": {"port": 18000},
        "programs": {
            "test-tool": {
                "description": "Test tool",
            },
            "test-daemon": {
                "description": "Test daemon program",
            },
        },
        "services": {
            # A path deployment — its `path` runner makes test-tool's behavior
            # derive as "tool" (behavior is derived from deployments, not stored).
            "test-tool": {
                "program": "test-tool",
                "run": {"runner": "path"},
            },
            # A process deployment — its systemd-managed runner makes test-daemon's
            # behavior derive as "daemon".
            "test-daemon": {
                "program": "test-daemon",
                "run": {"runner": "python", "program": "test-daemon"},
                "manage": {"systemd": {}},
            },
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
