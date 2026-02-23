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
castle create my-api --type service --description "Does something useful"
cd components/my-api && uv sync
castle test my-api
castle service enable my-api
castle gateway reload

# Standalone tool — CLI tool with argparse, stdin/stdout, Unix pipes
castle create my-tool --type tool --description "Does something"
```

## CLI Reference

```
castle list [--role ROLE] [--json]    List all components
castle info NAME [--json]             Show component details
castle create NAME --type TYPE        Scaffold a new component
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

`castle.yaml` is the single source of truth. Components declare **what they do** (run, expose, manage, install, build, triggers) and roles are **derived** from those declarations.

```yaml
gateway:
  port: 9000

components:
  central-context:
    description: Content storage API
    source: components/central-context
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

  notification-bridge:
    description: Desktop notification forwarder
    source: components/notification-bridge
    run:
      runner: python
      tool: notification-bridge
    defaults:
      env:
        CENTRAL_CONTEXT_URL: http://localhost:9001
        BUCKET_NAME: notifications
    expose:
      http:
        internal: { port: 9002 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /notifications }
    manage:
      systemd: {}
```

Convention-based env vars (`<PREFIX>_DATA_DIR`, `<PREFIX>_PORT`) are generated
automatically by `castle deploy`. Only non-convention values need `defaults.env`.

## Architecture

```
castle.yaml          <- component registry (single source of truth)
cli/                 <- castle CLI
castle-api/          <- Castle API (dashboard backend)
app/                 <- Castle web app (React/Vite frontend)
components/          <- all non-infrastructure components
  central-context/   <- content storage API (git submodule)
  notification-bridge/ <- desktop notification forwarder (git submodule)
  protonmail/        <- email sync tool/job
  devbox-connect/    <- SSH tunnel manager
  pdf2md/            <- standalone tool (each tool is its own project)
  ...
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
