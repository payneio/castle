# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

Castle is a personal software platform — a monorepo of independent projects
(services, tools, libraries) managed by the `castle` CLI. The registry
(`castle.yaml`) has three top-level sections:

- **`components:`** — Software catalog (source, install, tool metadata, build)
- **`services:`** — Long-running daemons (run, expose, proxy, systemd)
- **`jobs:`** — Scheduled tasks (run, cron schedule, systemd timer)

The section determines the category — no role derivation. Services and jobs
can reference a component via `component:` for description fallthrough.

**Key principle:** Regular projects must never depend on castle. They accept standard
configuration (data dir, port, URLs) via env vars. Only castle-components (CLI, gateway)
know about castle internals.

## Creating Components

When creating a new service, tool, or frontend, follow the detailed guides:

- @docs/component-registry.md — Registry architecture, castle.yaml structure, lifecycle
- @docs/web-apis.md — FastAPI service patterns (config, routes, models, testing)
- @docs/python-tools.md — CLI tool patterns (argparse, stdin/stdout, piping, testing)
- @docs/web-frontends.md — React/Vite/TypeScript frontend patterns

### Quick start

```bash
# Service
castle create my-service --type service --description "Does something"
cd components/my-service && uv sync
uv run my-service               # starts on auto-assigned port
castle service enable my-service # register with systemd
castle gateway reload            # update reverse proxy routes

# Tool
castle create my-tool --type tool --description "Does something"
cd components/my-tool && uv sync
```

The `castle create` command scaffolds the project under `components/`,
generates a CLAUDE.md, and registers it in `castle.yaml`.

## Castle CLI

The CLI lives in `cli/` and is installed via `uv tool install --editable cli/`.

```bash
castle list                              # List all components
castle list --type service               # Filter by category
castle info <component>                  # Show details (--json for machine-readable)
castle create <name> --type service      # Scaffold new project
castle test [project]                    # Run tests (one or all)
castle lint [project]                    # Run linter (one or all)
castle sync                              # Update submodules + uv sync all
castle run <component>                   # Run component in foreground
castle logs <component> [-f] [-n 50]     # View component logs
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

## Code Style

- **Linting/formatting**: ruff — shared `ruff.toml` at repo root (100-char lines)
- **Type checking**: pyright — shared `pyrightconfig.json` at repo root
- **Testing**: pytest, pytest-asyncio for async tests
- **Python**: 3.13 for services, 3.11+ minimum for tools/libraries

## Key Files

- `castle.yaml` — Component registry (three sections: components, services, jobs)
- `core/src/castle_core/manifest.py` — Pydantic models (ComponentSpec, ServiceSpec, JobSpec, RunSpec)
- `core/src/castle_core/config.py` — Config loader (castle.yaml → CastleConfig)
- `core/src/castle_core/generators/` — Systemd unit and Caddyfile generation
- `cli/src/castle_cli/templates/scaffold.py` — Project scaffolding templates
- `pyproject.toml` — uv workspace root (core, cli, castle-api)
- `ruff.toml` / `pyrightconfig.json` — Shared lint/type config
