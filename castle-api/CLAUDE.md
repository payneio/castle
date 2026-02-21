# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

castle-api is a FastAPI service. Castle API.

## Commands

```bash
uv sync                     # Install dependencies
uv run castle-api                 # Run service (port 9020)
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/castle_api/config.py` — Settings via pydantic-settings, env prefix `CASTLE_API_`
- `src/castle_api/main.py` — FastAPI app, lifespan, health endpoint
- `tests/` — pytest with TestClient fixtures

## Configuration

Environment variables with `CASTLE_API_` prefix:
- `CASTLE_API_DATA_DIR` — Data directory (default: ./data)
- `CASTLE_API_HOST` — Bind host (default: 0.0.0.0)
- `CASTLE_API_PORT` — Port (default: 9020)
