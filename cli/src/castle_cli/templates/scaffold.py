"""Project scaffolding - generates project files from templates."""

from __future__ import annotations

from pathlib import Path


def scaffold_project(
    project_dir: Path,
    name: str,
    package_name: str,
    proj_type: str,
    description: str,
    port: int | None = None,
) -> None:
    """Scaffold a new project from templates."""
    if proj_type == "service":
        _scaffold_service(project_dir, name, package_name, description, port or 9000)
    elif proj_type == "tool":
        _scaffold_tool(project_dir, name, package_name, description)
    elif proj_type == "library":
        _scaffold_library(project_dir, name, package_name, description)
    else:
        raise ValueError(f"Unknown project type: {proj_type}")


def _scaffold_service(
    project_dir: Path,
    name: str,
    package_name: str,
    description: str,
    port: int,
) -> None:
    """Scaffold a FastAPI service."""
    src_dir = project_dir / "src" / package_name
    tests_dir = project_dir / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    env_prefix = package_name.upper()

    # pyproject.toml
    _write(
        project_dir / "pyproject.toml",
        f'''[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "pydantic-settings>=2.0.0",
    "httpx>=0.27.0",
]

[project.scripts]
{name} = "{package_name}.main:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "httpx>=0.27.0",
]

[tool.ruff.lint.isort]
known-first-party = ["{package_name}"]
''',
    )

    # __init__.py
    _write(
        src_dir / "__init__.py",
        f'"""{description}."""\n\n__version__ = "0.1.0"\n',
    )

    # config.py
    _write(
        src_dir / "config.py",
        f'''"""Configuration for {name}."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables."""

    data_dir: Path = Path("./data")
    host: str = "0.0.0.0"
    port: int = {port}

    model_config = {{
        "env_prefix": "{env_prefix}_",
        "env_file": ".env",
    }}

    def ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
''',
    )

    # main.py
    _write(
        src_dir / "main.py",
        f'''"""Main application for {name}."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from {package_name}.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    settings.ensure_data_dir()
    yield


app = FastAPI(
    title="{name}",
    description="{description}",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {{"status": "ok"}}


def run() -> None:
    """Run the application with uvicorn."""
    uvicorn.run(
        "{package_name}.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
''',
    )

    # tests/__init__.py
    _write(tests_dir / "__init__.py", "")

    # tests/conftest.py
    _write(
        tests_dir / "conftest.py",
        f'''"""Test fixtures for {name}."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from {package_name}.config import settings
from {package_name}.main import app


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary data directory for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = settings.data_dir
    settings.data_dir = data_dir
    yield data_dir
    settings.data_dir = original


@pytest.fixture
def client(temp_data_dir: Path) -> Generator[TestClient, None, None]:
    """Create a test client with isolated data directory."""
    with TestClient(app) as client:
        yield client
''',
    )

    # tests/test_health.py
    _write(
        tests_dir / "test_health.py",
        f'''"""Tests for {name} health endpoint."""

from fastapi.testclient import TestClient


class TestHealth:
    """Health endpoint tests."""

    def test_health(self, client: TestClient) -> None:
        """Health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {{"status": "ok"}}
''',
    )

    # CLAUDE.md
    _write(
        project_dir / "CLAUDE.md",
        f"""# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

{name} is a FastAPI service. {description}.

## Commands

```bash
uv sync                     # Install dependencies
uv run {name}              # Run service (port {port})
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/{package_name}/config.py` — Settings via pydantic-settings, env prefix `{env_prefix}_`
- `src/{package_name}/main.py` — FastAPI app, lifespan, health endpoint
- `tests/` — pytest with TestClient fixtures

## Configuration

Environment variables with `{env_prefix}_` prefix:
- `{env_prefix}_DATA_DIR` — Data directory (default: ./data)
- `{env_prefix}_HOST` — Bind host (default: 0.0.0.0)
- `{env_prefix}_PORT` — Port (default: {port})
""",
    )


def _scaffold_tool(
    project_dir: Path,
    name: str,
    package_name: str,
    description: str,
) -> None:
    """Scaffold a CLI tool."""
    src_dir = project_dir / "src" / package_name
    tests_dir = project_dir / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    # pyproject.toml
    _write(
        project_dir / "pyproject.toml",
        f'''[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
{name} = "{package_name}.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
]

[tool.ruff.lint.isort]
known-first-party = ["{package_name}"]
''',
    )

    # __init__.py
    _write(
        src_dir / "__init__.py",
        f'"""{description}."""\n\n__version__ = "0.1.0"\n',
    )

    # main.py
    _write(
        src_dir / "main.py",
        f'''#!/usr/bin/env python3
"""{name}: {description}

Usage:
    {name} [options] [input]
    cat input.txt | {name}

Examples:
    {name} input.txt
    {name} input.txt -o output.txt
    cat input.txt | {name} > output.txt
"""

import argparse
import sys

from {package_name} import __version__

__all__ = ["main"]


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="{description}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input", nargs="?", help="Input file (default: stdin)")
    parser.add_argument(
        "-o", "--output", default=None, help="Output file (default: stdout)"
    )
    parser.add_argument(
        "--version", action="version", version=f"{name} {{__version__}}"
    )
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            data = f.read()
    else:
        data = sys.stdin.read()

    # TODO: implement tool logic
    result = data

    if args.output:
        with open(args.output, "w") as f:
            f.write(result)
    else:
        print(result, end="")

    return 0


if __name__ == "__main__":
    sys.exit(main())
''',
    )

    # tests/__init__.py
    _write(tests_dir / "__init__.py", "")

    # tests/test_main.py
    _write(
        tests_dir / "test_main.py",
        f'''"""Tests for {name}."""

import subprocess
import sys


class TestCLI:
    """CLI interface tests."""

    def test_version(self) -> None:
        """--version prints version string."""
        result = subprocess.run(
            [sys.executable, "-m", "{package_name}.main", "--version"],
            capture_output=True,
            text=True,
        )
        assert "{name}" in result.stdout
        assert "0.1.0" in result.stdout

    def test_stdin(self) -> None:
        """Reads from stdin when no file argument."""
        result = subprocess.run(
            [sys.executable, "-m", "{package_name}.main"],
            input="hello\\n",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_file_input(self, tmp_path) -> None:
        """Reads from file argument."""
        input_file = tmp_path / "input.txt"
        input_file.write_text("test data")
        result = subprocess.run(
            [sys.executable, "-m", "{package_name}.main", str(input_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "test data" in result.stdout

    def test_output_file(self, tmp_path) -> None:
        """Writes to output file with -o flag."""
        input_file = tmp_path / "input.txt"
        input_file.write_text("test data")
        output_file = tmp_path / "output.txt"
        result = subprocess.run(
            [
                sys.executable, "-m", "{package_name}.main",
                str(input_file), "-o", str(output_file),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output_file.read_text() == "test data"
''',
    )

    # CLAUDE.md
    _write(
        project_dir / "CLAUDE.md",
        f"""# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

{name} is a CLI tool. {description}.

## Commands

```bash
uv sync                     # Install dependencies
uv run {name}              # Run the tool
uv run {name} --version    # Show version
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/{package_name}/main.py` — Entry point, argparse CLI, stdin/stdout interface
- `src/{package_name}/__init__.py` — Package version (`__version__`)
- `tests/` — pytest tests

## Conventions

- Reads from stdin or file argument
- Writes to stdout or `-o/--output` file
- `--version` flag for version info
- Returns 0 on success, 1 on error
- Composable via Unix pipes
- `argparse.RawDescriptionHelpFormatter` with module docstring as epilog
""",
    )


def _scaffold_library(
    project_dir: Path,
    name: str,
    package_name: str,
    description: str,
) -> None:
    """Scaffold a Python library."""
    src_dir = project_dir / "src" / package_name
    tests_dir = project_dir / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)

    # pyproject.toml
    _write(
        project_dir / "pyproject.toml",
        f'''[project]
name = "{name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/{package_name}"]

[dependency-groups]
dev = [
    "pytest>=7.0.0",
]

[tool.ruff.lint.isort]
known-first-party = ["{package_name}"]
''',
    )

    # __init__.py
    _write(
        src_dir / "__init__.py",
        f'"""{description}."""\n\n__version__ = "0.1.0"\n',
    )

    # tests/__init__.py
    _write(tests_dir / "__init__.py", "")

    # tests/test_placeholder.py
    _write(
        tests_dir / "test_placeholder.py",
        f'''"""Tests for {name}."""


class TestPlaceholder:
    """Placeholder tests."""

    def test_import(self) -> None:
        """Library can be imported."""
        import {package_name}
        assert {package_name}.__version__ == "0.1.0"
''',
    )

    # CLAUDE.md
    _write(
        project_dir / "CLAUDE.md",
        f"""# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

{name} is a Python library. {description}.

## Commands

```bash
uv sync                     # Install dependencies
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/{package_name}/` — Library source code
- `tests/` — pytest tests
""",
    )


def _write(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
