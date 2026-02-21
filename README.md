# Castle

A declarative local control plane. Castle manages a collection of independent services, tools, and libraries from a single CLI, with a unified gateway, systemd integration, and standardized project scaffolding.

## Quick Start

```bash
# Install the castle CLI
cd cli && uv tool install --editable . && cd ..

# Sync all projects (git submodules + dependencies)
castle sync

# See what's here
castle list

# Start everything (all services + Caddy gateway)
castle services start

# Visit the dashboard
open http://localhost:9000
```

## Creating Projects

```bash
castle create my-api --type service --description "Does something useful"
cd my-api && uv sync
castle test my-api
castle service enable my-api
```

Three project types are supported:

- **service** — FastAPI app with health endpoint, pydantic-settings, systemd unit, gateway route
- **tool** — CLI tool with argparse, stdin/stdout, Unix pipe conventions
- **library** — Python package with src/ layout, no entry point

## CLI Reference

```
castle list [--type TYPE] [--json]    List all projects
castle create NAME --type TYPE        Scaffold a new project
castle test [PROJECT]                 Run tests (one or all)
castle lint [PROJECT]                 Run linter (one or all)
castle sync                           Update submodules + install deps
castle gateway start|stop|reload      Manage Caddy reverse proxy
castle service enable|disable NAME    Manage a systemd service
castle service status                 Show all service statuses
castle services start|stop            Start/stop everything
```

## Registry

`castle.yaml` at the repo root is the single source of truth. It defines every project's type, port, gateway path, data directory, command, and environment variables. The CLI reads this for all operations — generating Caddyfiles, systemd units, and dashboard HTML.

```yaml
gateway:
  port: 9000

projects:
  central-context:
    type: service
    port: 9001
    path: /central-context
    command: uv run central-context
    working_dir: central-context
    data_dir: /data/castle/central-context
    description: Content storage API
    health: /health
    env:
      CENTRAL_CONTEXT_DATA_DIR: ${data_dir}
```

## Architecture

```
castle.yaml          ← project registry
cli/                 ← castle CLI (castle-component)
central-context/     ← content storage API (git submodule)
notification-bridge/ ← notification forwarder (git submodule)
devbox-connect/      ← SSH tunnel manager
mboxer/              ← MBOX converter (git submodule)
toolkit/             ← personal utility scripts (git submodule)
event-bus/           ← inter-service event bus (castle-component)
ruff.toml            ← shared lint config
pyrightconfig.json   ← shared type checking config
```

**Independence principle:** Regular projects never depend on castle. They accept configuration (data dir, port, URLs) via environment variables. Only castle-components (CLI, gateway, event bus) know about castle internals like `castle.yaml`. This keeps projects portable and independently publishable.

**Gateway:** Caddy reverse proxy at port 9000. All services are accessible under one address (`localhost:9000/central-context/*` → `localhost:9001/*`). A dashboard with live health checks is served at the root.

**Systemd:** The CLI generates user units under `~/.config/systemd/user/castle-*.service`. `castle services start` brings up everything in one command.

**Data:** Service data lives in `/data/castle/<service-name>/`, outside the repo. Secrets live in `~/.castle/secrets/`.

## Current Projects

| Project | Type | Port | Description |
|---------|------|------|-------------|
| central-context | service | 9001 | Content storage API |
| notification-bridge | service | 9002 | Desktop notification forwarder |
| devbox-connect | tool | — | SSH tunnel manager |
| mboxer | tool | — | MBOX to EML converter |
| toolkit | tool | — | Personal utility scripts |
| event-bus | castle-component | 9010 | Inter-service event bus |
