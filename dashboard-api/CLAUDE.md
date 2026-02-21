# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

dashboard-api is a FastAPI service. Castle dashboard API.

## Commands

```bash
uv sync                     # Install dependencies
uv run dashboard-api              # Run service (port 9020)
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/dashboard_api/config.py` — Settings via pydantic-settings, env prefix `DASHBOARD_API_`
- `src/dashboard_api/main.py` — FastAPI app, lifespan, health endpoint
- `tests/` — pytest with TestClient fixtures

## Configuration

Environment variables with `DASHBOARD_API_` prefix:
- `DASHBOARD_API_DATA_DIR` — Data directory (default: ./data)
- `DASHBOARD_API_HOST` — Bind host (default: 0.0.0.0)
- `DASHBOARD_API_PORT` — Port (default: 9020)
