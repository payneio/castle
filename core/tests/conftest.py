"""Shared fixtures for castle core tests."""

from __future__ import annotations

import os as _os
from collections.abc import Generator
from pathlib import Path

# Tests must not read the host's real secret backend (castle.yaml may point
# at OpenBao); force the file backend unless CI explicitly overrides.
_os.environ.setdefault("CASTLE_SECRET_BACKEND", "file")

import pytest
import yaml


def _modernize_deployment(spec: dict) -> dict:
    """Translate a test's legacy deployment dict to the current manager-discriminated
    shape. Production dropped this read-compat once every machine migrated; the tests
    keep authoring the terse legacy shape, so the translation lives here instead.

    - ``proxy``/``public`` booleans → ``reach`` (internal/public).
    - ``run.runner`` → ``manager`` (+ ``run.launcher`` for the systemd process kinds).
    """
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
    """The deployments/<store>/ subdir for a (modernized) deployment spec."""
    if spec.get("schedule"):
        return "jobs"
    return {
        "systemd": "services",
        "caddy": "statics",
        "path": "tools",
        "none": "references",
    }[spec["manager"]]


def write_castle_config(root: Path, config: dict) -> None:
    """Scatter a nested castle config dict into the on-disk layout.

    `config` uses the terse nested shape (gateway/repo at top level, plus
    programs/services/jobs mappings); this writes castle.yaml with globals, one file
    per program under programs/, and each deployment under deployments/<kind>/ after
    modernizing its legacy fields (see `_modernize_deployment`).
    """
    globals_data = {k: v for k, v in config.items() if k in ("gateway", "repo")}
    (root / "castle.yaml").write_text(yaml.dump(globals_data, default_flow_style=False))

    programs = config.get("programs") or {}
    if programs:
        (root / "programs").mkdir(parents=True, exist_ok=True)
        for name, spec in programs.items():
            (root / "programs" / f"{name}.yaml").write_text(
                yaml.dump(spec, default_flow_style=False)
            )

    for section in ("services", "jobs", "deployments"):
        for name, spec in (config.get(section) or {}).items():
            modern = _modernize_deployment(spec)
            store_dir = root / "deployments" / _store_for(modern)
            store_dir.mkdir(parents=True, exist_ok=True)
            (store_dir / f"{name}.yaml").write_text(
                yaml.dump(modern, default_flow_style=False)
            )


@pytest.fixture
def castle_root(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary castle root with directory-per-resource config."""
    config = {
        "gateway": {"port": 18000},
        "programs": {
            "test-tool": {
                "description": "Test tool",
            },
        },
        "services": {
            "test-tool": {
                "program": "test-tool",
                "run": {"runner": "path"},
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
    write_castle_config(tmp_path, config)

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
