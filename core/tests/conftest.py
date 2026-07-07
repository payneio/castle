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


def write_castle_config(root: Path, config: dict) -> None:
    """Scatter a nested castle config dict into the directory-per-resource layout.

    `config` uses the legacy nested shape (gateway/repo at top level, plus
    programs/services/jobs mappings); this writes castle.yaml with globals and
    one file per resource under programs/, services/, jobs/.
    """
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
