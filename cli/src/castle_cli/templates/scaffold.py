"""Project scaffolding - generates project files from templates."""

from __future__ import annotations

from pathlib import Path


def scaffold_project(
    project_dir: Path,
    name: str,
    package_name: str,
    stack: str,
    description: str,
    port: int | None = None,
) -> None:
    """Scaffold a new project from templates based on stack."""
    if stack == "python-fastapi":
        _scaffold_service(project_dir, name, package_name, description, port or 9000)
    elif stack == "python-cli":
        _scaffold_tool(project_dir, name, package_name, description)
    elif stack == "supabase":
        _scaffold_supabase(project_dir, name, description)
    else:
        raise ValueError(f"No scaffold template for stack: {stack}")


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


def _scaffold_supabase(project_dir: Path, name: str, description: str) -> None:
    """Scaffold a Patch-shaped app that targets the shared Supabase substrate.

    Produces migrations/ (applied to the substrate by `castle program build`),
    functions/ (deno edge functions), public/ (static UI served in place at
    /<name>/ by the gateway), and supabase.app.yaml (auth policy + wiring).

    The app owns its code and stays repo-durable; only its rows/blobs live on the
    shared substrate. Each app is isolated in its **own Postgres schema** (the app
    id) rather than sharing `public` — so `castle program build` creates+grants the
    schema and tracks migrations per-app, and `castle delete --purge-data` drops
    the whole schema cleanly. Rows are further protected by RLS.
    """
    ident = name.replace("-", "_")  # a safe SQL/JS identifier — and the app schema
    table = "entries"  # unqualified; lives in the app's own schema (search_path)

    def sub(text: str) -> str:
        return (
            text.replace("__NAME__", name)
            .replace("__IDENT__", ident)
            .replace("__SCHEMA__", ident)
            .replace("__TABLE__", table)
            .replace("__DESC__", description)
        )

    # --- supabase.app.yaml — app manifest (substrate wiring + auth policy) ---
    _write(
        project_dir / "supabase.app.yaml",
        sub(
            """# Patch-shaped app targeting the shared Supabase substrate.
name: __NAME__
description: __DESC__
substrate: supabase          # the shared castle service this app deploys against

# auth policy: public | private | shared
#   public  — anyone with the URL (anon read/write, still RLS-gated)
#   private — only the owner; RLS locks rows to auth.uid()
#   shared  — owner + named people (list handles below)
auth: public
# shared: [alice, bob]

# This app is isolated in its own Postgres schema (created + exposed through
# PostgREST by `castle program build`). The frontend selects it via
# supabase-js `db: { schema }`.
schema: __SCHEMA__
"""
        ),
    )

    # --- migrations/0001_init.sql — versioned, idempotent, forward-only ---
    _write(
        project_dir / "migrations" / "0001_init.sql",
        sub(
            """-- 0001_init: example table + RLS. Applied by `castle program build`
-- via the versioned migration runner (tracked per-app in
-- <schema>.schema_migrations; only unapplied migrations run). Forward-only —
-- never edit an applied migration; add a new numbered file instead.
--
-- The runner sets search_path to this app's own schema, so unqualified names
-- land there (NOT in public). Keep tables unqualified for schema portability.

create table if not exists __TABLE__ (
    id          bigint generated always as identity primary key,
    message     text not null check (char_length(message) <= 500),
    author      text,
    created_at  timestamptz not null default now()
);

-- RLS is necessary but NOT sufficient on its own: it protects rows, not the
-- static app shell or Storage objects. For a `public` app, anon read/write is
-- intended (still row-gated). For `private`/`shared`, replace the policies below
-- with owner checks (auth.uid()) AND gate the shell + use signed Storage URLs.
alter table __TABLE__ enable row level security;

drop policy if exists "__IDENT___public_read" on __TABLE__;
create policy "__IDENT___public_read"  on __TABLE__ for select using (true);

drop policy if exists "__IDENT___public_write" on __TABLE__;
create policy "__IDENT___public_write" on __TABLE__ for insert with check (true);
"""
        ),
    )

    # --- functions/hello/index.ts — deno edge-function stub ---
    _write(
        project_dir / "functions" / "hello" / "index.ts",
        sub(
            """// Edge function for __NAME__. Runs on the substrate's edge-runtime.
// Deployed alongside migrations; call it from the app (never expose the
// service_role key to the browser — privileged work happens here, server-side).
import { serve } from "https://deno.land/std@0.208.0/http/server.ts";

serve((_req: Request) => {
  return new Response(
    JSON.stringify({ ok: true, app: "__NAME__", ts: new Date().toISOString() }),
    { headers: { "content-type": "application/json" } },
  );
});
"""
        ),
    )

    # --- public/config.js — substrate wiring (anon key is public-safe by design) ---
    _write(
        project_dir / "public" / "config.js",
        sub(
            """// Substrate wiring for __NAME__. The anon key is designed to be public
// (RLS enforces access) — paste yours here, or inject at deploy time:
//   cat ~/.castle/secrets/SUPABASE_ANON_KEY
window.APP = {
  SUPABASE_URL: "https://supabase.lan",
  SUPABASE_ANON_KEY: "PASTE_ANON_KEY_HERE",
  SCHEMA: "__SCHEMA__",   // this app's isolated Postgres schema
  TABLE: "__TABLE__",
};
"""
        ),
    )

    # --- public/index.html — reads/writes the substrate via supabase-js ---
    _write(
        project_dir / "public" / "index.html",
        sub(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__NAME__</title>
  <script src="./config.js"></script>
  <script type="module">
    import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
    const { SUPABASE_URL, SUPABASE_ANON_KEY, SCHEMA, TABLE } = window.APP;
    const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, { db: { schema: SCHEMA } });

    const list = document.getElementById("list");
    async function refresh() {
      const { data, error } = await db.from(TABLE)
        .select("message, author, created_at")
        .order("created_at", { ascending: false }).limit(50);
      list.textContent = error ? "Error: " + error.message
        : (data.map(r => `${r.author ?? "anon"}: ${r.message}`).join("\\n") || "(empty)");
    }
    document.getElementById("form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = e.target.message.value.trim();
      if (!message) return;
      const { error } = await db.from(TABLE).insert({ message });
      if (error) { alert(error.message); return; }
      e.target.reset();
      refresh();
    });
    refresh();
  </script>
</head>
<body>
  <h1>__NAME__</h1>
  <p>__DESC__</p>
  <form id="form"><input name="message" placeholder="Say something…" autocomplete="off" />
    <button>Post</button></form>
  <pre id="list">Loading…</pre>
</body>
</html>
"""
        ),
    )

    # --- CLAUDE.md — how this app works ---
    _write(
        project_dir / "CLAUDE.md",
        sub(
            """# __NAME__

__DESC__

A **supabase-stack** app: it owns its code (this repo) and rents its backend from
the shared Supabase substrate (the `supabase` castle service). Only its rows/blobs
live on the substrate; rebuild the rest from git anytime.

## Layout
- `migrations/` — versioned, idempotent Postgres migrations (forward-only). Applied
  to the substrate by `castle program build __NAME__`.
- `functions/` — deno edge functions deployed to the substrate's edge-runtime.
- `public/` — static UI served in place at `/__NAME__/` by the gateway. Talks to
  the substrate with `@supabase/supabase-js` + the public anon key (RLS-gated).
- `supabase.app.yaml` — substrate wiring + auth policy (public/private/shared).

## Develop
- Edit `migrations/`, then `castle program build __NAME__` to apply new migrations
  (re-running is a no-op — only unapplied migrations run).
- Set the anon key in `public/config.js` (`cat ~/.castle/secrets/SUPABASE_ANON_KEY`).
- `castle deploy && castle gateway reload` → served at `/__NAME__/`.

## Privacy note
RLS protects rows, not the static shell or Storage. For a `private`/`shared` app,
also gate the shell and use signed Storage URLs — RLS alone is not leak-proof.
Auth/WebCrypto apps should get their own HTTPS host route (secure context).
"""
        ),
    )


def _write(path: Path, content: str) -> None:
    """Write content to a file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
