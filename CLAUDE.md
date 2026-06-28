# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working
with code in this repository.

## Overview

Castle is a personal software platform — a monorepo of independent projects
(services, tools, libraries) managed by the `castle` CLI. The registry config is split into three directories under your config root:

- **`programs/`** — Software catalog (source, behavior, stack, system_dependencies, build)
- **`services/`** — Long-running daemons (run, expose, proxy, systemd)
- **`jobs/`** — Scheduled tasks (run, cron schedule, systemd timer)

Each program has a **stack** (development toolchain: python-fastapi,
python-cli, react-vite) and a **behavior** (runtime role: daemon, tool,
frontend). Scheduling, systemd management, and proxying are orthogonal
operations. Services and jobs reference a program via `program:` for
description fallthrough.

**Key principle:** Regular projects must never depend on castle. They accept standard
configuration (data dir, port, URLs) via env vars. Only castle programs (CLI, gateway)
know about castle internals.

## Programs: create new, or adopt existing

A **program** is a source repo castle knows how to work with (dev verbs) and
deploy. There are two ways to get one:

- **`castle program create`** — scaffold *new* code from a **stack** (a
  creation-time template). Stacks are guidance for how new code is written; they
  are NOT required at runtime.
- **`castle program add`** — adopt an *existing* repo (a local path or git URL),
  wherever it lives. No stack needed — castle detects sensible dev-verb commands
  (pyproject→uv/ruff/pytest, Cargo.toml→cargo, etc.) or you declare them.

**Stacks vs programs** are decoupled: a stack seeds a new program's default
verb commands and scaffold, but a program stands on its own via its declared
`commands:` (and `source:`/`repo:`). A program may have no stack at all.

Stack guides (for writing *new* code, AI-facing):

- @docs/registry.md — Registry architecture, castle.yaml structure, lifecycle
- @docs/stacks/python-fastapi.md — FastAPI service patterns (config, routes, models, testing)
- @docs/stacks/python-cli.md — CLI tool patterns (argparse, stdin/stdout, piping, testing)
- @docs/stacks/react-vite.md — React/Vite/TypeScript frontend patterns

### Quick start

```bash
# New daemon, scaffolded from a stack
castle program create my-service --stack python-fastapi --description "Does something"
cd /data/repos/my-service && uv sync
castle service create my-service --program my-service --port 9001   # declare the service
castle service deploy my-service && castle service enable my-service # unit + start
castle gateway reload                                                # update reverse proxy routes

# New tool from a stack
castle program create my-tool --stack python-cli --description "Does something"

# Adopt an existing repo (no stack required)
castle program add ~/projects/some-rust-tool
castle program add https://github.com/me/widget.git --name widget
```

`castle program create` scaffolds under `/data/repos/` (override with
`CASTLE_REPOS_DIR`) and registers the program in `castle.yaml` with an absolute
`source:`. `castle program add` registers an existing repo in place (or records
its `repo:` URL for `castle program clone`).

## Castle CLI

The CLI lives in `cli/` and is installed via `uv tool install --editable cli/`.

The CLI is **resource-first**: operations live under the resource they act on
(`program`, `service`, `job`, `gateway`). Names can collide across resource
types (a program and a service may share a name), so the resource is explicit.
Platform-wide lifecycle and the cross-resource overview are top-level.

```bash
# Programs — the software catalog
castle program list [--behavior daemon] [--stack python-cli] [--json]
castle program info <name> [--json]
castle program create <name> [--stack ...] [--description ...]   # scaffold new
castle program add <path|git-url> [--name ...]                   # adopt existing repo
castle program clone [name]                                      # clone repo: source
castle program delete <name> [--source] [-y]
castle program run <name> [args...]                              # declared run command
castle program install|uninstall [name]                          # activate tools/frontends
castle program build|test|lint|format|type-check|check [name]    # dev verbs

# Services — long-running daemons
castle service list [--json]
castle service info <name> [--json]
castle service create <name> [--program P] [--port N] [--health ...] \
                      [--path ...] [--host ...] [--port-env ...] [--runner ...]
castle service delete <name> [-y]
castle service deploy <name>                                     # generate unit + route
castle service enable|disable <name>                             # systemd enable/disable
castle service start|stop|restart <name>                         # systemd lifecycle (one)
castle service logs <name> [-f] [-n 50]

# Jobs — scheduled tasks (same verbs; create takes --schedule)
castle job create <name> [--program P] --schedule "0 2 * * *" [--runner ...]
castle job <list|info|delete|deploy|enable|disable|start|stop|restart|logs> ...

# Platform-wide (top-level)
castle list [--behavior ...] [--stack ...] [--json]   # programs + services + jobs
castle status                                         # unified status
castle deploy [name]                                  # apply config → units + Caddyfile
castle start | stop | restart                         # all services (+ gateway)
castle gateway start|stop|reload|status               # the Caddy gateway
```

Bringing everything online is the two honest steps `castle deploy && castle
start` (apply config, then start) — there is no bundled `up`.

**Dev verbs** resolve per-program: a declared `commands:` entry (or `build:`)
overrides the stack default, falling back to the program's stack handler, else
the verb is unavailable. So a wired-in repo with **no `stack`** works as long as
it declares its commands. Tools are reached via `castle program list --behavior tool`.

## Infrastructure

Castle uses two roots, each overridable by an env var: `CASTLE_HOME` (config,
code, artifacts, secrets; default `~/.castle`) and `CASTLE_DATA_DIR` (program
data I/O on a dedicated volume; default `/data/castle`). Paths below use
`$CASTLE_HOME` and `$CASTLE_DATA_DIR` accordingly.

- **Gateway**: Caddy at port 9000 — both a reverse proxy (to local/remote
  services) and a static file server (for built frontends, served in place from
  `<source>/<dist>`). Config generated from `castle.yaml` into
  `$CASTLE_HOME/artifacts/specs/Caddyfile`. A route maps an address (path or
  host) to a target of kind static/proxy/remote; `castle gateway status` lists
  them. Dashboard (castle-app) served at root.
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

Deployments (the unified view of services + jobs + programs):
- `GET /deployments` — List all (add `?include_remote=true` for cross-node)
- `GET /deployments/{name}` — Deployment detail
- `GET /status` — Live health for all services

Programs / Services / Jobs (typed views + editing):
- `GET /programs`, `GET /programs/{name}` — Program catalog (`?behavior=tool` to filter)
- `POST /programs/{name}/{action}` — Run a program verb (install/uninstall/build/…)
- `PUT|DELETE /programs/{name}` — Edit or remove a program entry
- `GET /services`, `GET /services/{name}`, `PUT|DELETE /services/{name}`
- `GET /jobs`, `GET /jobs/{name}`, `PUT|DELETE /jobs/{name}`

Config:
- `GET /` — Full registry; `PUT /` — Save registry
- `POST /apply` — Apply registry changes; `POST /deploy` — Deploy to runtime

Gateway:
- `GET /gateway` — Gateway info + full route table (every route tagged kind=static|proxy|remote, with its address and target)
- `GET /gateway/caddyfile` — Generated Caddyfile content
- `POST /gateway/reload` — Regenerate Caddyfile and reload Caddy

Mesh:
- `GET /mesh/status` — MQTT connection state, broker info, peer list
- `GET /nodes` — All known nodes (local + discovered remote)
- `GET /nodes/{hostname}` — Node detail with deployed components

Service actions:
- `POST /services/{name}/{action}` — start/stop/restart
- `GET /services/{name}/unit` — Systemd unit content

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
