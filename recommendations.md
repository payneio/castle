# Scaling Recommendations

## Decisions made

- **Git structure**: Monorepo with submodules. Castle is a git repo; projects that need independent publishing are their own repos added as submodules. Projects without remotes (e.g., devbox-connect) are tracked directly until they get their own repo.
- **Scope**: Castle is a personal software platform — not just services, but tools, libraries, and apps. Toolkit (v1, CLI tools only) is being absorbed and generalized.
- **Gateway**: Caddy reverse proxy + generated dashboard. Single port for all web services. Caddy chosen over Traefik because the service registry is static (no container orchestration), and Caddyfile syntax is trivially simple.
- **Event bus**: A lightweight castle-component for inter-service communication, so services don't hardcode knowledge of each other.
- **Independence principle**: Regular services/tools/libraries must never depend on castle. They accept standard configuration (data dir, port, URLs) via env vars or args. Only "castle-components" (CLI, gateway, event bus) know about castle internals like `castle.yaml`. This keeps services portable and independently publishable.
- **Registry**: `castle.yaml` at the repo root. Centralized — all projects are registered here. `castle create` adds entries automatically. No marker files in projects (would violate independence principle).
- **Discovery**: Centralized via `castle.yaml`. The CLI reads this file to know what projects exist, their types, and how to orchestrate them.
- **CLI location**: `cli/` directory at the repo root, installed via `uv tool install`.
- **Generated files**: `~/.castle/generated/` for Caddyfiles, systemd units, dashboard HTML. Separate from `~/.castle/secrets/`.

## 1. Build the `castle` CLI

The top-level CLI lives in `cli/` and is installed via `uv tool install`. It replaces both toolkit's `toolkit` command and the need for a Makefile/justfile. It should:
- Discover projects by type (tool, service, library, app) from `castle.yaml`
- Scaffold new projects from templates: `castle create <name> --type service`
- Run commands across projects: `castle test`, `castle lint`, `castle sync`
- Wrap submodule pain points: `castle sync` does `git submodule update --init --recursive`
- Manage services: `castle service enable/disable/status`, `castle services start/stop`
- Manage gateway: `castle gateway start/reload`
- Register `uv tool` entries for tool-type projects

This generalizes toolkit's discovery/scaffolding pattern (YAML frontmatter in markdown, `toolkit create`) across all project types.

## 2. Define project type templates

Each type encodes best practices:
- **tool**: argparse, stdin/stdout, exit codes, single-purpose (toolkit pattern)
- **service**: FastAPI, pydantic-settings, lifespan, health endpoint
- **library**: src/ layout, typed API, no CLI entry point
- **app**: TBD as needs emerge

Shared patterns (settings base class, error handling, test fixtures) live in templates rather than a shared library — avoids a runtime dependency that couples all projects.

## 3. Standardize project layout

Pick `src/<package_name>/` for all projects. Currently inconsistent: `src/central_context/`, flat `notification_bridge/`, single-file `convert.py`. The castle CLI's discovery and scaffolding depends on predictable structure.

## 4. Registry, gateway, and systemd

`castle.yaml` at the repo root is the single source of truth for all projects — their types, ports, paths, data directories, commands, and inter-service relationships.

The castle CLI generates artifacts from this registry into `~/.castle/generated/`:
- **Caddyfile** — reverse proxy config so all services are accessible under one port (e.g., `localhost:9000/central-context/*` → `localhost:9001/*`)
- **Dashboard HTML** — served at the gateway root (`localhost:9000/`) with links to each service, health status, and docs links
- **Systemd user units** — `.service` files under `~/.config/systemd/user/`

Example `castle.yaml`:
```yaml
gateway:
  port: 9000

projects:
  # Services (long-running, have ports)
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

  notification-bridge:
    type: service
    port: 9001
    path: /notifications
    command: uv run notification-bridge
    working_dir: notification-bridge
    data_dir: /data/castle/notification-bridge
    description: Desktop notification forwarder
    health: /health
    publishes:
      - notification.received

  devbox-connect:
    type: tool
    description: SSH tunnel manager with auto-reconnect

  mboxer:
    type: tool
    description: MBOX to EML email converter

  # Castle-components
  event-bus:
    type: castle-component
    port: 9010
    path: /events
    command: uv run event-bus
    description: Inter-service event bus
```

### Gateway commands

```
castle gateway start    # generate Caddyfile + dashboard, start Caddy
castle gateway reload   # regenerate after castle.yaml changes
```

### Systemd commands

```
castle service enable central-context   # generate unit, enable, start
castle service disable central-context  # stop and disable
castle service status                   # show status of all services
castle services start                   # enable + start everything (including gateway)
castle services stop                    # stop everything
```

The gateway itself is also a systemd unit (`castle-gateway.service`), so `castle services start` brings up all services and the Caddy proxy in one command.

Castle resolves `${data_dir}` references, ensures data directories exist, and passes env vars when generating units.

## 5. Agent context strategy

The primary value of castle is that agents can rapidly create and manage software in a standardized way. The conventions must be machine-discoverable.

- **Top-level `CLAUDE.md`** is the agent's entry point into the entire system. It should reference `castle.yaml`, explain project types, link to templates, and describe the agent workflow (scaffold → register → test → enable).
- **`castle create` updates context automatically** — when a new project is scaffolded, the CLI generates a project-level `CLAUDE.md` from the template and registers the project in `castle.yaml`.
- **Each project type template includes a `CLAUDE.md` template** so agents immediately understand a project's conventions, build commands, and architecture upon reading it.
- **The agent workflow is explicit**: an agent creating a new service follows: `castle create` → implement → `castle test` → `castle service enable`. No tribal knowledge required.

## 6. Data persistence conventions

As castle replaces commercial applications, the data these services hold becomes the valuable part. Conventions:

- **Each service's data dir is configured in `castle.yaml`** — defaults to `/data/castle/<service-name>/`. Castle supplies this to the service at launch (via env var or arg). The service itself just accepts a data dir setting — it has no knowledge of castle.
- **Data directories are never inside submodule trees** — submodules get cloned fresh; persistent data must live outside them.
- **Backup stays generic** — `backup-collect` remains a general-purpose tool. It doesn't read `castle.yaml`. Castle can separately generate a backup manifest from the registry if needed, but that's a castle concern, not a backup-collect concern.

## 7. Secret management

API keys, tokens, and credentials will accumulate as services replace commercial apps. Rules:

- **Secrets live in `~/.castle/secrets/`** — never in project directories (submodules get pushed to GitHub). Agents must be told this explicitly in context.
- **`castle.yaml` can reference secrets by name** — the castle CLI resolves them when generating systemd units or passing env vars at launch. Services themselves just receive env vars — they don't know where the values came from.

## 8. Event bus

A castle-component that decouples inter-service communication. Currently notification-bridge hardcodes central-context's URL — this won't scale to dozens of services that need to react to each other's events.

The event bus is a FastAPI service registered in `castle.yaml`:
- Services **publish** typed events: `POST /events/publish` with `{topic, payload}`
- Services **subscribe** to topics: register a webhook callback in `castle.yaml` or via `POST /events/subscribe`
- The bus delivers events to subscribers via HTTP POST to their registered endpoints

This keeps services decoupled — a service only knows about the bus, not about other services. Example flow: notification-bridge publishes a `notification.received` event, and any service that cares subscribes to that topic.

Subscriptions are declared in `castle.yaml` (see example above). The castle CLI configures the bus with the subscription table at startup.

The bus should be simple — no persistence, no guaranteed delivery, no complex routing. Just HTTP fan-out. Add durability later only if needed.

## 9. Consistent ruff/pyright configuration

Each project has its own ruff rules (devbox-connect: `E,F,I,W`; mboxer: `ALL`). Put a shared `ruff.toml` at the repo root (ruff walks up to find config). Same for pyright — only devbox-connect has it currently.

## 10. Absorb toolkit

Don't move toolkit in as a monolith. Instead:
1. Add toolkit as a submodule
2. Graduate heavy tools (`search`, `protonmail`, `browser`) into independent castle projects
3. Keep lightweight tools (`docx2md`, `html2text`, etc.) grouped in a single `tools` package
4. Promote toolkit's meta-tooling up into the castle CLI

## 11. What to defer

- **Shared runtime library (`castle-core`)** — templates are better than a runtime dependency for now. Revisit if projects start importing shared code at runtime.
- **Containerization/orchestration** — until deploying beyond the local machine
- **API gateway / service mesh** — Caddy handles reverse proxying; a full mesh is premature
- **Distributed tracing / observability** — add when debugging cross-service issues becomes painful
- **Formal API schema sharing** — FastAPI generates OpenAPI already; formalize when consumers need stability guarantees

## Priority

1. **Castle CLI** with project discovery and scaffolding
2. **Registry** (`castle.yaml`) + **Caddy gateway** + **systemd integration**
3. **Agent context strategy** — CLAUDE.md generation in templates, agent workflow docs
4. **Data persistence conventions** + **secret management**
5. **Standardize layout** across existing projects
6. **Root-level ruff/pyright config**
7. **Event bus** castle-component
8. **Absorb toolkit** incrementally
