# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

event-bus is a castle-component — a lightweight inter-service event bus for HTTP fan-out.
Services publish typed events to topics, other services subscribe with webhook callback URLs.
No persistence, no guaranteed delivery — just simple HTTP POST fan-out.

## Commands

```bash
uv sync                     # Install dependencies
uv run event-bus            # Run service (port 9010)
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Architecture

- `src/event_bus/config.py` — Settings via pydantic-settings, env prefix `EVENT_BUS_`
- `src/event_bus/main.py` — FastAPI app, endpoints: publish, subscribe, unsubscribe, topics, health
- `src/event_bus/bus.py` — Core EventBus class with in-memory subscription table and async HTTP delivery
- `tests/` — pytest with TestClient fixtures

## API

- `POST /publish` — `{"topic": "...", "payload": {...}}` — fan-out to subscribers
- `POST /subscribe` — `{"topic": "...", "callback_url": "...", "subscriber": "..."}` — register webhook
- `POST /unsubscribe` — `{"topic": "...", "callback_url": "..."}` — remove subscription
- `GET /topics` — list all topics and their subscribers
- `GET /health` — health check

## Configuration

Environment variables with `EVENT_BUS_` prefix:
- `EVENT_BUS_DATA_DIR` — Data directory (default: ./data)
- `EVENT_BUS_HOST` — Bind host (default: 0.0.0.0)
- `EVENT_BUS_PORT` — Port (default: 9010)
