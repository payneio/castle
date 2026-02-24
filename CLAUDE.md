# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

Castle is a personal software platform — a monorepo of independent projects
(services, tools, libraries) managed by the `castle` CLI. The registry
(`castle.yaml`) has three top-level sections:

- **`programs:`** — Software catalog (source, behavior, stack, system_dependencies, build)
- **`services:`** — Long-running daemons (run, expose, proxy, systemd)
- **`jobs:`** — Scheduled tasks (run, cron schedule, systemd timer)

Each program has a **stack** (development toolchain: python-fastapi,
python-cli, react-vite) and a **behavior** (runtime role: daemon, tool,
frontend). Scheduling, systemd management, and proxying are orthogonal
operations. Services and jobs reference a program via `component:` for
description fallthrough.

**Key principle:** Regular projects must never depend on castle. They accept standard
configuration (data dir, port, URLs) via env vars. Only castle programs (CLI, gateway)
know about castle internals.

## Creating Programs

When creating a new service, tool, or frontend, follow the detailed guides:

- @docs/component-registry.md — Registry architecture, castle.yaml structure, lifecycle
- @docs/stacks/python-fastapi.md — FastAPI service patterns (config, routes, models, testing)
- @docs/stacks/python-cli.md — CLI tool patterns (argparse, stdin/stdout, piping, testing)
- @docs/stacks/react-vite.md — React/Vite/TypeScript frontend patterns

### Quick start

```bash
# Daemon (python-fastapi)
castle create my-service --stack python-fastapi --description "Does something"
cd programs/my-service && uv sync
uv run my-service               # starts on auto-assigned port
castle service enable my-service # register with systemd
castle gateway reload            # update reverse proxy routes

# Tool (python-cli)
castle create my-tool --stack python-cli --description "Does something"
cd programs/my-tool && uv sync
```

The `castle create` command scaffolds the project under `programs/`,
generates a CLAUDE.md, and registers it in `castle.yaml`.

## Castle CLI

The CLI lives in `cli/` and is installed via `uv tool install --editable cli/`.

```bash
castle list                              # List all programs, services, and jobs
castle list --behavior daemon             # Filter by behavior
castle list --stack python-cli           # Filter by stack
castle info <name>                       # Show details (--json for machine-readable)
castle create <name> --stack python-fastapi  # Scaffold new project
castle deploy [name]                     # Deploy to runtime (registry + systemd + Caddyfile)
castle test [project]                    # Run tests (one or all)
castle lint [project]                    # Run linter (one or all)
castle sync                              # Update submodules + uv sync all
castle run <name>                        # Run service in foreground
castle logs <name> [-f] [-n 50]          # View service/job logs
castle tool list                         # List all tools
castle tool info <name>                  # Show tool details
castle gateway start|stop|reload|status  # Manage Caddy reverse proxy
castle service enable|disable <name>     # Manage individual systemd service
castle service status                    # Show all service statuses
castle services start|stop               # Start/stop everything
```

## Infrastructure

- **Gateway**: Caddy reverse proxy at port 9000, config generated from `castle.yaml`
  into `~/.castle/generated/Caddyfile`. Dashboard served at root.
- **Systemd**: User units generated under `~/.config/systemd/user/castle-*.service`.
  Use drop-in overrides (`*.service.d/*.conf`) for extra env vars that `castle deploy`
  shouldn't overwrite (e.g., `CASTLE_API_MQTT_ENABLED`).
- **Containers**: `runner: container` services use Docker (preferred on this system
  due to rootless podman UID mapping issues). Deploy resolves the runtime via
  `shutil.which("docker")`.
- **MQTT**: Mosquitto broker runs as `castle-mqtt` (Docker container on port 1883).
  Data in `/data/castle/castle-mqtt/`, config in `/data/castle/castle-mqtt/config/`.
- **Data**: Service data lives in `/data/castle/<service-name>/`, passed via env var.
- **Secrets**: `~/.castle/secrets/` — never in project directories.

## API Endpoints (castle-api, port 9020)

Core:
- `GET /health` — Health check
- `GET /stream` — SSE stream (health, service-action, mesh events)

Components:
- `GET /components` — List all (add `?include_remote=true` for cross-node)
- `GET /components/{name}` — Component detail
- `GET /status` — Live health for all services

Gateway:
- `GET /gateway` — Gateway info with route table and hostname
- `GET /gateway/caddyfile` — Generated Caddyfile content
- `POST /gateway/reload` — Regenerate Caddyfile and reload Caddy

Mesh:
- `GET /mesh/status` — MQTT connection state, broker info, peer list
- `GET /nodes` — All known nodes (local + discovered remote)
- `GET /nodes/{hostname}` — Node detail with deployed components

Services:
- `POST /services/{name}/{action}` — start/stop/restart
- `GET /services/{name}/unit` — Systemd unit content

Tools:
- `GET /tools` — List all tools
- `GET /tools/{name}` — Tool detail
- `POST /tools/{name}/install` — Install tool to PATH
- `POST /tools/{name}/uninstall` — Uninstall tool

## Mesh Coordination (opt-in)

Multi-node discovery is disabled by default. Enable via env vars:

```bash
CASTLE_API_MQTT_ENABLED=true    # Connect to MQTT broker
CASTLE_API_MQTT_HOST=localhost   # Broker address
CASTLE_API_MQTT_PORT=1883        # Broker port
CASTLE_API_MDNS_ENABLED=true    # Advertise/discover via mDNS
```

Key modules: `castle_api.mesh` (MeshStateManager), `castle_api.mqtt_client`
(paho-mqtt wrapper), `castle_api.mdns` (python-zeroconf wrapper).

## Per-Project Commands

All projects use **uv**. Commands run from each project's directory:

```bash
uv sync                     # Install deps
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

Services also support: `uv run <service-name>` to start.

## Code Style

- **Linting/formatting**: ruff — shared `ruff.toml` at repo root (100-char lines)
- **Type checking**: pyright — shared `pyrightconfig.json` at repo root
- **Testing**: pytest, pytest-asyncio for async tests
- **Python**: 3.13 for services, 3.11+ minimum for tools/libraries

## Key Files

- `castle.yaml` — Registry (three sections: programs, services, jobs)
- `core/src/castle_core/manifest.py` — Pydantic models (ProgramSpec, ServiceSpec, JobSpec, RunSpec)
- `core/src/castle_core/config.py` — Config loader (castle.yaml → CastleConfig)
- `core/src/castle_core/generators/` — Systemd unit and Caddyfile generation
- `cli/src/castle_cli/templates/scaffold.py` — Project scaffolding templates
- `pyproject.toml` — uv workspace root (core, cli, castle-api)
- `ruff.toml` / `pyrightconfig.json` — Shared lint/type config
