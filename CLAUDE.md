# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

Castle is a personal software platform — a monorepo of independent projects
(services, tools, libraries) managed by the `castle` CLI. Components declare
**what they do** (expose HTTP, manage via systemd, install to PATH) and roles
are **derived**, not labeled.

**Key principle:** Regular projects must never depend on castle. They accept standard
configuration (data dir, port, URLs) via env vars. Only castle-components (CLI, gateway,
event bus) know about castle internals.

## Castle CLI

The CLI lives in `cli/` and is installed via `uv tool install --editable cli/`.

```bash
castle list                              # List all components
castle list --role service               # Filter by derived role
castle info <component>                  # Show manifest details (--json for machine-readable)
castle create <name> --type service      # Scaffold new project
castle test [project]                    # Run tests (one or all)
castle lint [project]                    # Run linter (one or all)
castle sync                              # Update submodules + uv sync all
castle run <component>                   # Run component in foreground
castle logs <component> [-f] [-n 50]     # View component logs
castle gateway start|stop|reload|status  # Manage Caddy reverse proxy
castle service enable|disable <name>     # Manage individual systemd service
castle service status                    # Show all service statuses
castle services start|stop               # Start/stop everything
castle migrate                           # Convert castle.yaml to new format
```

## Registry & Manifest Architecture

`castle.yaml` at the repo root is the single source of truth. It uses a **manifest**
model (`cli/src/castle_cli/manifest.py`) where components declare capabilities:

- **`run`**: How to start it (RunSpec: `python_uv_tool`, `command`, `container`, `node`, `remote`)
- **`expose`**: What it exposes (HTTP port, health endpoint)
- **`proxy`**: How to proxy it (Caddy path prefix)
- **`manage`**: How to manage it (systemd)
- **`install`**: How to install it (PATH shim)
- **`build`**: How to build it (commands, outputs)
- **`triggers`**: What triggers it (manual, schedule, event, request)

**Roles are derived** from these declarations:
- `service` — has `expose.http`
- `tool` — has `install.path` or is fallback
- `worker` — has `manage.systemd` but no HTTP
- `job` — has schedule trigger
- `frontend` — has build outputs
- `containerized` — uses container runner
- `remote` — uses remote runner

## Component Roles (replaces Project Types)

| Role | Convention | Example |
|------|-----------|---------|
| **service** | FastAPI, pydantic-settings, lifespan, `/health` endpoint | central-context |
| **tool** | argparse, stdin/stdout, exit codes, Unix pipes | devbox-connect |
| **worker** | Systemd-managed, no HTTP | (none yet) |
| **job** | Scheduled task | (none yet) |
| **containerized** | Docker/Podman container | (none yet) |

## Creating a New Project

```bash
castle create my-service --type service --description "Does something"
cd my-service
uv sync
uv run my-service       # starts on auto-assigned port
castle test my-service   # run tests
castle service enable my-service  # register with systemd
```

The `castle create` command scaffolds the project, generates a CLAUDE.md, and registers
it in `castle.yaml` as a `ComponentManifest`.

## Infrastructure

- **Gateway**: Caddy reverse proxy at port 9000, config generated from `castle.yaml`
  into `~/.castle/generated/Caddyfile`. Dashboard served at root.
- **Systemd**: User units generated under `~/.config/systemd/user/castle-*.service`
- **Data**: Service data lives in `/data/castle/<service-name>/`, passed via env var.
- **Secrets**: `~/.castle/secrets/` — never in project directories.

## Per-Project Commands

All projects use **uv**. Commands run from each project's directory:

```bash
uv sync                     # Install deps
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

Services also support: `uv run <service-name>` to start.

## Existing Components

| Component | Roles | Port | Description |
|-----------|-------|------|-------------|
| central-context | service | 9001 | Content storage API (submodule) |
| notification-bridge | service | 9002 | Desktop notification forwarder (submodule) |
| devbox-connect | tool | — | SSH tunnel manager |
| mboxer | tool | — | MBOX to EML converter (submodule) |
| toolkit | tool | — | Personal utility scripts (submodule) |
| protonmail | tool | — | ProtonMail email sync via Bridge |
| event-bus | service | 9010 | Inter-service event bus |

## Code Style

- **Linting/formatting**: ruff — shared `ruff.toml` at repo root (100-char lines)
- **Type checking**: pyright — shared `pyrightconfig.json` at repo root
- **Testing**: pytest, pytest-asyncio for async tests
- **Python**: 3.13 for services, 3.11+ minimum for tools/libraries

## Agent Workflow

When creating a new service or tool:
1. `castle create <name> --type <type>` — scaffold and register
2. Implement the project logic
3. `castle test <name>` — verify tests pass
4. `castle service enable <name>` — deploy as systemd service (services only)
5. `castle gateway reload` — update reverse proxy routes
