# Castle

A personal software platform. Castle manages independent services, tools, and frontends from a single CLI, with a unified gateway, systemd integration, and a web dashboard.

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

## Creating Components

```bash
# Service — FastAPI app with health endpoint, systemd unit, gateway route
castle create my-api --stack python-fastapi --description "Does something useful"
cd components/my-api && uv sync
castle test my-api
castle service enable my-api
castle gateway reload

# Standalone tool — CLI tool with argparse, stdin/stdout, Unix pipes
castle create my-tool --stack python-cli --description "Does something"
```

## CLI Reference

```
castle list [--behavior B] [--stack S] [--json]  List all components
castle info NAME [--json]                        Show component details
castle create NAME --stack STACK                 Scaffold a new component
castle deploy [NAME]                  Deploy component(s) to runtime
castle run NAME                       Run component in foreground
castle test [NAME]                    Run tests (one or all)
castle lint [NAME]                    Run linter (one or all)
castle sync                           Update submodules + install deps
castle logs NAME [-f] [-n 50]         View component logs
castle gateway start|stop|reload      Manage Caddy reverse proxy
castle service enable|disable NAME    Manage a systemd service
castle service status                 Show all service statuses
castle services start|stop            Start/stop everything
castle tool list                      List all tools
castle tool info NAME                 Show tool details
```

## Registry

`castle.yaml` is the single source of truth with three sections:

- **`components:`** — Software catalog (source, install, tool metadata, build)
- **`services:`** — Long-running daemons (run, expose, proxy, systemd)
- **`jobs:`** — Scheduled tasks (run, cron schedule, systemd timer)

Services and jobs can reference a component via `component:` for description fallthrough.

```yaml
gateway:
  port: 9000

components:
  central-context:
    description: Content storage API
    source: components/central-context

services:
  central-context:
    component: central-context
    run:
      runner: python
      tool: central-context
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /central-context }
    manage:
      systemd: {}

jobs:
  backup-collect:
    component: backup-collect
    run:
      runner: command
      argv: [backup-collect]
    schedule: "0 2 * * *"
    manage:
      systemd: {}
```

Convention-based env vars (`<PREFIX>_DATA_DIR`, `<PREFIX>_PORT`) are generated
automatically by `castle deploy`. Only non-convention values need `defaults.env`.

## Architecture

```
castle.yaml          <- component registry (single source of truth)
cli/                 <- castle CLI
core/                <- castle-core library (models, config, generators)
castle-api/          <- Castle API (dashboard backend)
app/                 <- Castle web app (React/Vite frontend)
components/          <- all non-infrastructure components
  central-context/   <- content storage API (git submodule)
  notification-bridge/ <- desktop notification forwarder (git submodule)
  protonmail/        <- email sync tool/job
  pdf2md/            <- standalone tool (each tool is its own project)
  ...
docs/                <- architecture docs and component guides
ruff.toml            <- shared lint config
pyrightconfig.json   <- shared type checking config
```

**Independence principle:** Services never depend on castle. They accept configuration (data dir, port, URLs) via environment variables. Only castle components (CLI, API, gateway) know about castle internals.

**Gateway:** Caddy reverse proxy at port 9000. Services are proxied under one address (`localhost:9000/central-context/*` -> `localhost:9001/*`). The web app is served at the root.

**Systemd:** The CLI generates user units under `~/.config/systemd/user/castle-*.service`. Scheduled jobs get `.timer` files alongside.

**Data:** Service data lives in `/data/castle/<service-name>/`, outside the repo. Secrets live in `~/.castle/secrets/`.

## Components

### Services

| Component | Port | Description |
|-----------|------|-------------|
| castle-gateway | 9000 | Caddy reverse proxy gateway |
| central-context | 9001 | Content storage API |
| notification-bridge | 9002 | Desktop notification forwarder |
| castle-api | 9020 | Castle API (dashboard backend) |
| castle-mqtt | 1883 | MQTT broker for mesh coordination (Mosquitto container) |

### Jobs

| Component | Schedule | Description |
|-----------|----------|-------------|
| protonmail | Every 5 min | ProtonMail email sync |
| backup-collect | 2:00 AM | Collect files into backup directory |
| backup-data | 3:30 AM | Restic backup of /data to /storage |

### Tools

| Tool | Description |
|------|-------------|
| android-backup | Backup Android devices via ADB |
| browser | Browse the web via browser-use |
| devbox-connect | SSH tunnel manager |
| docx-extractor | Extract content from Word files |
| docx2md | Convert Word .docx to Markdown |
| gpt | OpenAI text generation |
| html2text | Convert HTML to plain text |
| mbox2eml | Convert MBOX mailboxes to .eml files |
| md2pdf | Convert Markdown to PDF |
| mdscraper | Combine text files into markdown |
| pdf-extractor | Extract content from PDF files |
| pdf2md | Convert PDF to Markdown |
| schedule | Manage systemd user timers |
| search | Manage searchable file collections |
| text-extractor | Extract content from text files |

### Frontends

| Component | Description |
|-----------|-------------|
| castle-app | Castle web dashboard (React/Vite/TypeScript) |

## Mesh Coordination

Castle nodes can discover each other via MQTT and mDNS, forming a personal infrastructure mesh. All mesh features are opt-in — single-node works without them.

```bash
# Enable on castle-api (via systemd drop-in or env vars)
CASTLE_API_MQTT_ENABLED=true     # Connect to MQTT broker
CASTLE_API_MQTT_HOST=localhost    # Broker address (default)
CASTLE_API_MQTT_PORT=1883         # Broker port (default)
CASTLE_API_MDNS_ENABLED=true     # Advertise/discover via mDNS
```

When enabled, the API publishes the node's registry to `castle/{hostname}/registry` (retained) and subscribes to other nodes. The gateway can proxy to services on remote nodes. The dashboard shows discovered nodes, cross-node routes, and mesh connection status.

## API

`castle-api` runs on port 9020 and is proxied at `/api` through the gateway.

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /stream` | SSE stream (health, service-action, mesh events) |
| `GET /components` | List all components (`?include_remote=true` for cross-node) |
| `GET /components/{name}` | Component detail |
| `GET /status` | Live health for all services |
| `GET /gateway` | Gateway info with route table |
| `GET /gateway/caddyfile` | Generated Caddyfile content |
| `POST /gateway/reload` | Regenerate Caddyfile and reload Caddy |
| `GET /mesh/status` | Mesh connection state (MQTT, mDNS, peers) |
| `GET /nodes` | All known nodes (local + remote) |
| `GET /nodes/{hostname}` | Node detail with deployed components |
| `POST /services/{name}/{action}` | Start/stop/restart a service |
| `GET /tools` | List all tools |
| `POST /tools/{name}/install` | Install tool to PATH |
