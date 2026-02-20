# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Castle is a monorepo of four independent Python projects that form personal infrastructure services. Each project has its own `pyproject.toml`, `uv.lock`, and dependencies.

| Project | Purpose | Layout |
|---------|---------|--------|
| **central-context** | REST API for storing/retrieving UTF-8 content in buckets | `src/central_context/` |
| **notification-bridge** | Cross-platform desktop notification forwarder | `notification_bridge/` (no src/) |
| **devbox-connect** | SSH tunnel manager with auto-reconnect | `src/devbox_connect/` |
| **mboxer** | MBOX to EML email converter | Single file `convert.py` |

## Build & Development Commands

All projects use **uv** as the package manager. Commands must be run from each project's directory.

### central-context
```bash
cd central-context
uv sync                     # Install deps
uv run central-context      # Run service (port 9000)
uv run pytest tests/ -v     # Run tests
uv run pytest tests/test_storage.py -v  # Single test file
```

### notification-bridge
```bash
cd notification-bridge
uv sync --extra linux       # Install deps (use --extra windows on Windows)
uv run notification-bridge  # Run service (port 9001)
uv run pytest --cov=notification_bridge  # Run tests with coverage
uv run ruff format .        # Format
uv run ruff check .         # Lint
```

### devbox-connect
```bash
cd devbox-connect
uv sync                     # Install deps
uv tool install .           # Install as CLI tool
devbox-connect -c tunnels.yaml start     # Start tunnels
devbox-connect -c tunnels.yaml status    # Show status
devbox-connect -c tunnels.yaml validate  # Validate config
```

### mboxer
```bash
cd mboxer
uv sync             # Install deps
python convert.py   # Run converter (configure via .env)
ruff check . --fix  # Lint
```

## Architecture

**central-context** is the hub — notification-bridge forwards captured desktop notifications to it via its REST API. The API organizes content into buckets (filesystem directories), auto-names entries by SHA256 checksum, and stores JSON metadata sidecars alongside content files.

**notification-bridge** uses a platform adapter pattern: `listeners/base.py` defines a `NotificationListener` protocol, with `linux.py` (D-Bus) and `windows.py` (WinRT) implementations. The server captures notifications and POSTs them to central-context.

**devbox-connect** manages persistent SSH tunnels defined in YAML config. It supports two config formats: simple (flat list) and grouped (by host). Tunnels auto-reconnect with exponential backoff. Has Windows service support via NSSM.

## Configuration

- **central-context**: Env vars with `CENTRAL_CONTEXT_` prefix, pydantic-settings
- **notification-bridge**: `.env` file (`CENTRAL_CONTEXT_URL`, `BUCKET_NAME`, `PORT`)
- **devbox-connect**: YAML config file (`tunnels.yaml`)
- **mboxer**: `.env` file (`MBOX_PATH`, `OUTPUT_DIR`)

## Code Style

- **Linting/formatting**: ruff (project-specific configs in each `pyproject.toml`)
- **devbox-connect**: 100-char line length, pyright type checking at standard level, Python 3.10+
- **central-context / notification-bridge**: Python 3.13, FastAPI
- **Testing**: pytest with pytest-asyncio for async tests
