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

## Programs: create new, or adopt existing

A **program** is a source repo castle knows how to work with (dev verbs) and
deploy. There are two ways to get one:

- **`castle create`** — scaffold *new* code from a **stack** (a creation-time
  template). Stacks are guidance for how new code is written; they are NOT
  required at runtime.
- **`castle add`** — adopt an *existing* repo (a local path or git URL),
  wherever it lives. No stack needed — castle detects sensible dev-verb commands
  (pyproject→uv/ruff/pytest, Cargo.toml→cargo, etc.) or you declare them.

**Stacks vs programs** are decoupled: a stack seeds a new program's default
verb commands and scaffold, but a program stands on its own via its declared
`commands:` (and `source:`/`repo:`). A program may have no stack at all.

Stack guides (for writing *new* code, AI-facing):

- @docs/component-registry.md — Registry architecture, castle.yaml structure, lifecycle
- @docs/stacks/python-fastapi.md — FastAPI service patterns (config, routes, models, testing)
- @docs/stacks/python-cli.md — CLI tool patterns (argparse, stdin/stdout, piping, testing)
- @docs/stacks/react-vite.md — React/Vite/TypeScript frontend patterns

### Quick start

```bash
# New daemon, scaffolded from a stack
castle create my-service --stack python-fastapi --description "Does something"
cd /data/repos/my-service && uv sync
castle service enable my-service   # register with systemd
castle gateway reload              # update reverse proxy routes

# New tool from a stack
castle create my-tool --stack python-cli --description "Does something"

# Adopt an existing repo (no stack required)
castle add ~/projects/some-rust-tool
castle add https://github.com/me/widget.git --name widget
```

`castle create` scaffolds under `/data/repos/` (override with `CASTLE_REPOS_DIR`)
and registers the program in `castle.yaml` with an absolute `source:`. `castle add`
registers an existing repo in place (or records its `repo:` URL for `castle clone`).

## Castle CLI

The CLI lives in `cli/` and is installed via `uv tool install --editable cli/`.

```bash
castle list                              # List all programs, services, and jobs
castle list --behavior daemon             # Filter by behavior
castle list --stack python-cli           # Filter by stack
castle info <name>                       # Show details (--json for machine-readable)
castle create <name> [--stack ...]       # Scaffold new project (--stack optional → bare program)
castle add <path|git-url> [--name ...]   # Adopt an EXISTING repo as a program (detects verbs)
castle clone [name]                      # Clone source for programs that declare repo:
castle deploy [name]                     # Deploy to runtime (registry + systemd + Caddyfile)
castle build|test|lint|type-check|check [project]   # Dev verbs (one or all)
castle install|uninstall [program]       # Install/remove a program on PATH
castle run <name>                        # Run a program (declared run) or service in foreground
castle logs <name> [-f] [-n 50]          # View service/job logs
castle gateway start|stop|reload|status  # Manage Caddy reverse proxy
castle service enable|disable <name>     # Manage individual systemd service
castle service status                    # Show all service statuses
castle services start|stop               # Start/stop everything
```

**Dev verbs** resolve per-program: a declared `commands:` entry (or `build:`)
overrides the stack default, falling back to the program's stack handler, else
the verb is unavailable. So a wired-in repo with **no `stack`** works as long as
it declares its commands. Tools are reached via `castle list --behavior tool`
(the dedicated `castle tool` command was removed).

## Infrastructure

Castle uses two roots, each overridable by an env var: `CASTLE_HOME` (config,
code, artifacts, secrets; default `~/.castle`) and `CASTLE_DATA_DIR` (program
data I/O on a dedicated volume; default `/data/castle`). Paths below use
`$CASTLE_HOME` and `$CASTLE_DATA_DIR` accordingly.

- **Gateway**: Caddy reverse proxy at port 9000, config generated from `castle.yaml`
  into `$CASTLE_HOME/artifacts/specs/Caddyfile`. Dashboard served at root.
- **Systemd**: User units generated under `~/.config/systemd/user/castle-*.service`.
  Use drop-in overrides (`*.service.d/*.conf`) for extra env vars that `castle deploy`
  shouldn't overwrite (e.g., `CASTLE_API_MQTT_ENABLED`).
- **Containers**: `runner: container` services use Docker (preferred on this system
  due to rootless podman UID mapping issues). Deploy resolves the runtime via
  `shutil.which("docker")`.
- **MQTT**: Mosquitto broker runs as `castle-mqtt` (Docker container on port 1883).
  Data in `$CASTLE_DATA_DIR/castle-mqtt/`, config in `$CASTLE_DATA_DIR/castle-mqtt/config/`.
- **Data**: Service data lives in `$CASTLE_DATA_DIR/<service-name>/` (default
  `/data/castle/<name>/`), passed via the generated `<PREFIX>_DATA_DIR` env var.
- **Secrets**: `$CASTLE_HOME/secrets/` — never in project directories.

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
