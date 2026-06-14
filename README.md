# Castle

"Standing to author, run, govern, and maintain your own software"

A personal software platform. Castle manages independent services, tools, and frontends from a single CLI, with a unified gateway, systemd integration, and a web dashboard.

Historically, applications have been developed by third parties, distributed through app stores, and installed on user devices.

With the advent of AI-assisted software development, users can write the software they need directly, eliminating the need for packaging and distribution. This makes many classes of software simpler, too. Oftentimes all a user needs are simple scripts or configurations of existing tools. But no matter how simple your script or application, it needed to be tailored and packaged for specific distribution channels. Castle provides a unified environment for developing, managing, deploying, and advertising these simple applications.

Castle _stacks_ are pre-configured development environments that provide a starting point for building applications. They include everything needed to get started, from the programming language and framework to the necessary dependencies and tools. This is a design intended for coding assistants to generate castle programs with a level of consistency and to ensure that they are properly configured and ready to use with Castle. If your coding assistant knows about Castle, it can help you create and manage your custom applications more efficiently.

## Quick Start

```bash
# Install the castle CLI
cd cli && uv tool install --editable . && cd ..

# Run the installer (sets up Docker, Caddy, MQTT, Postgres, Neo4j, directory tree)
./install.sh

# Initialize castle.yaml (the registry that tracks everything)
cat > ~/.castle/castle.yaml << 'EOF'
gateway:
  port: 9000

programs: {}
services: {}
jobs: {}
EOF

# See what's here
castle list

# Deploy and start everything
castle deploy
castle services start

# Visit the dashboard
open http://localhost:9000
```

## Creating Components

```bash
# Service — FastAPI app with health endpoint, systemd unit, gateway route
castle create my-api --stack python-fastapi --description "Does something useful"
castle test my-api
castle deploy my-api
castle services start

# Standalone tool — CLI tool with argparse, stdin/stdout, Unix pipes
castle create my-tool --stack python-cli --description "Does something"

# Frontend — React/Vite app, built and served through the gateway
castle create my-app --stack react-vite --description "Web interface"
castle build my-app
castle deploy my-app
```

## CLI Reference

```
castle list [--behavior B] [--stack S] [--json]  List all programs, services, and jobs
castle info NAME [--json]                        Show program details
castle create NAME [--stack STACK]               Scaffold a new project (bare if no stack)
castle add PATH|GIT-URL [--name N]               Adopt an existing repo as a program
castle clone [NAME]                   Clone source for programs that declare repo:
castle build|test|lint|type-check|check [NAME]   Dev verbs (one or all)
castle install|uninstall [NAME]       Install/remove a program on PATH
castle deploy [NAME]                  Deploy to ~/.castle/ (spec -> runtime)
castle run NAME                       Run a program (declared run) or service in foreground
castle logs NAME [-f] [-n 50]         View service/job logs
castle gateway start|stop|reload      Manage Caddy reverse proxy
castle service enable|disable NAME    Manage a systemd service
castle service status                 Show all service statuses
castle services start|stop            Start/stop everything
```

Tools are programs with `behavior: tool` — list them with
`castle list --behavior tool`.

## Registry

`castle.yaml` lives at `~/.castle/castle.yaml` and is the single source of truth. It has four top-level sections:

- **`programs:`** — Software catalog (source, stack, behavior, build config)
- **`services:`** — Long-running daemons (run, expose, proxy, systemd)
- **`jobs:`** — Scheduled tasks (run, cron schedule, systemd timer)
- **`units:`** — Compact shorthand that expands into programs + services/jobs

Services and jobs can reference a program via `component:` for description fallthrough.

```yaml
gateway:
  port: 9000
repo: /path/to/castle

programs:
  central-context:
    description: Content storage API
    behavior: daemon
    source: code/central-context
    stack: python-fastapi

services:
  central-context:
    component: central-context
    run:
      runner: python
      program: central-context
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

The optional `repo:` field enables `source: repo:<path>` references that resolve relative to the git repo rather than `~/.castle/`.

## Architecture

```
~/.castle/
  castle.yaml          <- program registry (single source of truth)
  code/                <- component source directories
  data/                <- per-service data directories
  secrets/             <- secret files (700 permissions)
  artifacts/
    specs/             <- generated Caddyfile, registry.yaml, systemd units
    content/           <- built frontend assets

<repo>/
  cli/                 <- castle CLI
  core/                <- castle-core library (models, config, generators)
  castle-api/          <- Castle API (dashboard backend)
  app/                 <- Castle web app (React/Vite frontend)
  docs/                <- architecture docs
  install.sh           <- infrastructure bootstrapper
```

**Independence principle:** Services never depend on castle. They accept configuration (data dir, port, URLs) via environment variables. Only castle infrastructure (CLI, API, gateway) knows about castle internals.

**Gateway:** Caddy reverse proxy at port 9000. Services are proxied under one address (`localhost:9000/central-context/*` -> `localhost:9001/*`). The web app is served at the root.

**Systemd:** The CLI generates user units under `~/.config/systemd/user/castle-*.service`. Scheduled jobs get `.timer` files alongside.

**Data:** Service data lives in `~/.castle/data/<service-name>/`. Secrets live in `~/.castle/secrets/`.

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
| **Programs** | |
| `GET /programs` | List all programs (`?behavior=tool\|daemon\|frontend` to filter) |
| `GET /programs/{name}` | Program detail |
| `POST /programs/{name}/{action}` | Run a lifecycle action (build, test, lint, install, etc.) |
| `GET /components` | Unified view across nodes (`?include_remote=true` for cross-node) |
| `GET /components/{name}` | Component detail |
| **Services** | |
| `GET /services` | List all services with status |
| `GET /services/{name}` | Service detail |
| `POST /services/{name}/start` | Start a service |
| `POST /services/{name}/stop` | Stop a service |
| `POST /services/{name}/restart` | Restart a service |
| `GET /services/{name}/unit` | View generated systemd unit |
| **Jobs** | |
| `GET /jobs` | List all jobs |
| `GET /jobs/{name}` | Job detail |
| **Gateway** | |
| `GET /gateway` | Gateway info with route table |
| `GET /gateway/caddyfile` | Generated Caddyfile content |
| `POST /gateway/reload` | Regenerate Caddyfile and reload Caddy |
| `GET /status` | Live health for all services |
| **Deploy** | |
| `POST /deploy` | Deploy all services and jobs (spec to runtime) |
| **Config** | |
| `GET /config` | Read castle.yaml |
| `PUT /config` | Write castle.yaml |
| `PUT /config/programs/{name}` | Update a program entry |
| `PUT /config/services/{name}` | Update a service entry |
| `PUT /config/jobs/{name}` | Update a job entry |
| `POST /config/apply` | Apply config changes (deploy + reload) |
| **Secrets** | |
| `GET /secrets` | List secrets |
| `GET /secrets/{name}` | Read a secret |
| `PUT /secrets/{name}` | Write a secret |
| `DELETE /secrets/{name}` | Delete a secret |
| **Logs** | |
| `GET /logs/{name}` | View service/job logs |
| **Mesh** | |
| `GET /mesh/status` | Mesh connection state (MQTT, mDNS, peers) |
| `GET /nodes` | All known nodes (local + remote) |
| `GET /nodes/{hostname}` | Node detail with deployed components |
