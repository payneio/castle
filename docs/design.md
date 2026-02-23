# Castle Design

Castle is a personal software platform. It manages independent services,
tools, and frontends on a Linux machine using standard Unix primitives —
systemd for process supervision, Caddy for HTTP routing, the filesystem
for storage, and env vars for configuration. The `castle` CLI and API
provide a registry and coordination layer on top.

The long-term goal: multiple Castle nodes (machines) that discover each
other and coordinate, forming a personal infrastructure mesh. Each node
is self-sufficient. The mesh is optional.

## Principles

1. **Unix-native.** Use the OS. systemd, journald, filesystem, signals,
   env vars, DNS. Don't reimplement what Linux already provides.

2. **Independence.** Components never depend on Castle. They accept
   standard configuration (ports, data dirs, URLs) via env vars. A
   Castle service is just a well-behaved Unix daemon that happens to
   be registered in a manifest.

3. **Section is category.** Components, services, and jobs live in
   separate sections of `castle.yaml`. The section determines the
   category — no role derivation needed.

4. **Language-agnostic above the build line.** Below the build line,
   every language is different (uv, pnpm, cargo, go). Above it,
   everything is just processes, ports, files, and signals. Castle
   operates above the line.

5. **Separate source from runtime.** The repo is for development. The
   runtime lives in standard Unix locations (`~/.castle/`, `/data/castle/`,
   systemd units). Nothing running should point into the source tree.

6. **AI-manageable.** The CLI and API exist so that AI assistants can
   discover, create, and manage components programmatically. Humans
   use the dashboard. Agents use the CLI and API.

7. **Simple until proven otherwise.** Filesystem over databases. HTTP
   over custom protocols. Shell commands over plugin systems. Add
   complexity only when the simple thing actually fails.

## Architecture Layers

```
┌─────────────────────────────────────────────┐
│  Coordination                               │
│  Node discovery, global registry, messaging │
├─────────────────────────────────────────────┤
│  Registry                                   │
│  Component spec, node config, CLI, API      │
├─────────────────────────────────────────────┤
│  Runtime                                    │
│  systemd, Caddy, filesystem, journald       │
├─────────────────────────────────────────────┤
│  Build                                      │
│  uv, pnpm, cargo, go build, etc.           │
└─────────────────────────────────────────────┘
```

The critical boundary is between Build and Runtime. Below it, each
language has its own toolchain. Above it, everything is uniform — a
process that reads env vars, listens on a port, logs to stdout, and
responds to SIGTERM.

### Build Layer

Transforms source code into runnable artifacts. Castle does not abstract
over language toolchains — it just records the build commands and their
outputs.

| Language | Toolchain | Artifact |
|----------|-----------|----------|
| Python | uv | Entry point in venv |
| Node/TS | pnpm | Static bundle (frontends) or node script |
| Rust | cargo | Binary |
| Go | go build | Binary |

Castle's `build` spec is intentionally minimal: a list of shell commands
and a list of output paths. This works for any language without Castle
needing to understand the toolchain.

For interpreted languages (Python, Node), Castle also needs to know the
runtime wrapper — how to invoke the artifact. This is what the `run`
spec's runner variants handle:

- `python` — Python (sync via uv, deploy resolves installed binary)
- `node` — Node.js (sync via pnpm/npm)
- `command` — Direct execution (compiled binaries, shell scripts)
- `container` — Docker/Podman
- `remote` — External service (no local process)

Compiled languages (Rust, Go) use `command` — once built, they're just
binaries. No Castle-specific runner needed.

### Runtime Layer

Manages running processes using standard Linux infrastructure.

**systemd** handles process supervision:
- Start/stop/restart services
- Restart-on-failure policies (OTP's "let it crash")
- Dependency ordering via `After=` / `Wants=`
- Scheduled execution via `.timer` units
- Logging via journald (stdout/stderr capture)

**Caddy** handles HTTP routing:
- Reverse proxy on port 9000
- Path-based routing to services (`/api` → port 9020)
- Static file serving for frontends
- TLS termination

**Filesystem** handles storage:
- Service data: `/data/castle/<name>/`
- Secrets: `~/.castle/secrets/`
- Generated config: `~/.castle/generated/`

Castle generates systemd unit files and Caddyfile entries from the
registry. It doesn't run a daemon itself — it configures OS-level
infrastructure and gets out of the way.

Critically, the runtime layer references only standard paths — never
the source tree. Systemd units point to installed binaries (on PATH
or in `~/.castle/bin/`), not to repo subdirectories. Caddy serves
from `~/.castle/static/`, not from build output directories in the repo.

### Registry Layer

The registry is the central concept in Castle. It tracks what components
exist, what they can do, and how they're configured. But it's not a
single thing — it's three distinct concepts:

**1. Component spec** — what a component *is*. Description, capabilities,
build instructions, default configuration. This is source-level
information, version-controlled in the repo. It answers: "what components
could exist?"

**2. Node config** — what's *deployed on this machine*, with what concrete
ports, data paths, and env vars. This is per-machine. Two Castle nodes
might run different subsets of components with different parameters. It
answers: "what's running here, and how?"

**3. Runtime state** — what's *actually happening*. PIDs, health, uptime,
logs. This is ephemeral, owned by systemd and queried on demand. It
answers: "is it working?"

#### Source vs. runtime split

These map to two files:

**`castle.yaml`** (in the repo, version-controlled) — Three sections:

```yaml
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
      caddy:
        path_prefix: /central-context
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

Components define *what software exists* (identity, source, install, tools).
Services define *how daemons run* (run config, expose, proxy, systemd).
Jobs define *how scheduled tasks run* (run config, cron schedule, systemd).

Services and jobs can reference a component via `component:` for description
fallthrough and source code linking. They can also exist independently
(e.g., `castle-gateway` runs Caddy — not our software).

Convention-based env vars (`<PREFIX>_PORT`, `<PREFIX>_DATA_DIR`) are
generated automatically during deploy. Only non-convention values need
`defaults.env`.

**`~/.castle/registry.yaml`** (per-node, not in the repo) — Node config:

```yaml
node:
  hostname: tower
  castle_root: /data/repos/castle
  gateway_port: 9000
deployed:
  central-context:
    runner: python
    run_cmd: [/home/user/.local/bin/central-context]
    env:
      CENTRAL_CONTEXT_DATA_DIR: /data/castle/central-context
      CENTRAL_CONTEXT_PORT: "9001"
    category: service
    port: 9001
    health_path: /health
    proxy_path: /central-context
    managed: true
```

The node config says what's deployed *here* and with what concrete
values. `castle deploy` reads the spec from the repo, generates
convention-based env vars, resolves secrets, resolves binary paths,
and writes the registry. Systemd units and Caddyfile are then generated
from the registry — never from the spec directly.

This separation means:
- The repo is just a repo. `git pull` doesn't affect running services.
- Multi-node works: sync the spec + deploy on each node, no repo needed.
- The spec is portable and version-controlled. The node config is local.
- AI agents read the node registry to know what's deployed and running.

#### Interfaces

Three interfaces expose the registry:

- **CLI** (`castle`) — For AI agents and terminal users. Structured
  output via `--json`. Commands for listing, inspecting, creating,
  and managing components.
- **API** (`castle-api`) — For programmatic access over HTTP. Used by
  the dashboard, other nodes, and remote agents.
- **Dashboard** (`castle-app`) — For human discoverability. Visual
  overview of what's running, health status, logs.

### Coordination Layer

*Partially built. This section describes the target architecture.*

Coordination handles discovery and communication — both between
components on a single node and across multiple Castle nodes.

**Intra-node coordination** (current):
- Components find each other through the gateway (path-based routing)
  or direct port access via env vars.
- The registry (CLI/API) provides discoverability.
- No service mesh or message broker required for basic operation.

**Inter-node coordination** (future):
- Each Castle node runs the API, which exposes its component registry.
- Nodes discover each other via MQTT retained messages or mDNS/DNS-SD
  (Avahi) for LAN environments.
- The gateway on each node can proxy to services on other nodes,
  preserving path-based routing. Components don't know which node
  they're talking to.
- MQTT provides pub/sub messaging for events, status, and coordination
  across nodes.

**Why MQTT over custom gossip:**
- Standard protocol, every language has a client library.
- Retained messages give new nodes an immediate view of the network.
- Topic-based routing maps naturally to `castle/{node}/{component}`.
- Works across networks (not just LAN like mDNS).
- Mosquitto is a single binary, simple to run as a Castle component.

**Why mDNS/DNS-SD as a complement:**
- Zero-config LAN discovery via Avahi (already on most Linux systems).
- Each node advertises `_castle._tcp` — standard tooling works
  (`avahi-browse`).
- Good for bootstrapping: find the MQTT broker without hardcoding
  its address.

## Component Contract

Every Castle component, regardless of language, must satisfy a minimal
contract. This is what makes the system uniform above the build line.

### Services (long-running daemons)

| Requirement | Mechanism |
|-------------|-----------|
| Accept configuration | Env vars (prefixed by service name) |
| Declare its port | Env var, registered in `expose.http.internal.port` |
| Health endpoint | `GET /health` returns 200 |
| Data storage | Read `*_DATA_DIR` env var, write there |
| Logging | stdout for output, stderr for errors |
| Graceful shutdown | Handle SIGTERM, exit cleanly |
| Secrets | Read from env vars (Castle resolves `${secret:NAME}`) |
| No Castle dependency | Must run standalone with just env vars set |

### Tools (CLI utilities)

| Requirement | Mechanism |
|-------------|-----------|
| Input | File argument or stdin |
| Output | stdout (pipeable) |
| Errors/status | stderr |
| Exit codes | 0 success, non-zero failure |
| No interactive prompts | Scriptable by default |

### Jobs (scheduled tasks)

Same contract as tools, plus:

| Requirement | Mechanism |
|-------------|-----------|
| Idempotent | Safe to re-run or run concurrently |
| Short-lived | Exit when done (oneshot systemd unit) |

## Component Lifecycle

The path from source to managed process:

```
source → [build] → artifact → [install] → available → [deploy] → managed
```

Each step is distinct:

1. **Build** — Language-specific. Produces an artifact (binary, venv
   entry point, static bundle). Castle records the commands but doesn't
   execute them implicitly.

2. **Install** — Makes the artifact available on the system. For tools:
   `uv tool install` or compiled binary placed in `~/.castle/bin/`. For
   services: same — the binary or entry point is on PATH or in a known
   location. For frontends: built assets copied to `~/.castle/static/`.

3. **Deploy** — Materializes the runtime configuration. Reads the
   component spec, merges with node config, generates systemd units
   and Caddyfile entries that reference *installed* artifacts — never
   the source tree. Enables and starts services.

For compiled languages (Rust, Go), build produces a standalone binary
and install is just placing it in `~/.castle/bin/`. For interpreted
languages (Python, Node), the runtime wrapper (uv, node) handles
finding the installed artifact.

## Runtime Filesystem Layout

What already exists and what the target looks like:

```
~/.castle/                      ← Castle runtime home
├── registry.yaml               ← Node config (what's deployed here)
├── generated/                  ← Generated Caddyfile
│   └── Caddyfile
├── secrets/                    ← Secret files (NAME → value)
│   └── PROTONMAIL_API_KEY
├── bin/                        ← Compiled binaries, shims
│   └── my-go-tool
└── static/                     ← Built frontend assets
    └── castle-app/
        └── dist/

/data/castle/                   ← Persistent service data
└── <name>/

~/.config/systemd/user/         ← Systemd units (standard location)
├── castle-central-context.service
├── castle-protonmail.service
├── castle-protonmail.timer
└── ...
```

Source (the repo) is referenced only during build and install. Everything
the runtime touches lives in `~/.castle/`, `/data/castle/`, or standard
systemd paths.

## OTP as Design Guide

Castle's architecture parallels Erlang/OTP, mapped onto Unix:

| OTP Concept | Castle Equivalent |
|-------------|------------------|
| Application | Component (independent, self-contained) |
| Application resource file | Component spec in `castle.yaml` |
| Release config (sys.config) | Node config in `~/.castle/registry.yaml` |
| Release assembly | `castle deploy` (spec + node config → runtime) |
| Supervisor | systemd (restart policies, ordering) |
| Process | Running service/worker/job |
| Application env | Env vars |
| Node | A machine running Castle |
| epmd | mDNS / MQTT discovery |
| Distribution | Inter-node coordination via MQTT + gateway proxying |
| "Let it crash" | `restart: on-failure` in systemd |
| Global registry | Merged node registries via MQTT retained messages |

The mapping is conceptual, not literal. Castle doesn't implement OTP
semantics — it uses OTP's *thinking* to guide which Unix primitives
to compose and how.

Key OTP ideas that apply:
- **Isolation.** Components don't share state. Communication is
  through explicit interfaces (HTTP, MQTT, filesystem paths).
- **Let it crash.** Services don't need elaborate error recovery.
  systemd restarts them. Design for restartability, not immortality.
- **Supervision hierarchy.** systemd's dependency ordering provides
  this. Services declare what they need to start after.
- **Location transparency.** Components talk to paths (`/api`,
  `/central-context`), not to specific hosts or ports. The gateway
  can remap these across nodes.
- **Spec vs. config.** In OTP, an application defines its structure
  (the `.app` file) and a release provides the deployment config
  (`sys.config`). Castle mirrors this: the component spec defines
  structure, the node config provides deployment values.

## Current State

What exists today:

- **CLI** — `castle` command, installed via `uv tool install --editable cli/`
- **Three packages** — `castle-core` (models, config, generators),
  `castle-cli` (commands), `castle-api` (HTTP API)
- **Source/runtime split** — `castle.yaml` (spec) → `castle deploy` →
  `~/.castle/registry.yaml` (node config). Systemd units and Caddyfile
  generated from registry with fully resolved paths. No repo references
  in runtime artifacts.
- **Convention-based env generation** — `castle deploy` auto-generates
  `<PREFIX>_DATA_DIR=/data/castle/<name>` and `<PREFIX>_PORT` from
  the manifest. Only non-convention values need `defaults.env`.
- **Gateway** — Caddy on port 9000, Caddyfile generated from registry
- **API** — `castle-api` on port 9020, reads from registry (optional
  castle.yaml fallback for non-deployed components)
- **Dashboard** — `castle-app` React/Vite frontend, static assets
  served from `~/.castle/static/castle-app/`
- **Services** — central-context (content storage), notification-bridge
  (desktop notification forwarder)
- **Jobs** — protonmail (email sync every 5 min), backup-collect (nightly),
  backup-data (nightly restic backup)
- **Tools** — ~15 CLI utilities (pdf2md, docx2md, search, gpt, etc.)
- **Manifest** — `castle.yaml` with typed Pydantic models

What doesn't exist yet:

- **Multi-language support** — Rust and Go components (the abstractions
  support them via `command` runner, but no examples exist yet)
- **Inter-node coordination** — MQTT broker, node discovery, cross-node
  routing
- **Build automation** — Castle records build specs but doesn't
  orchestrate builds (each project builds independently)

## Technology Map

| Concern | Technology | Status |
|---------|-----------|--------|
| Process supervision | systemd (user units) | Active |
| HTTP routing | Caddy (port 9000) | Active |
| Component specs | castle.yaml + Pydantic models | Active |
| Node config | `~/.castle/registry.yaml` | Active |
| CLI | castle (Python, uv) | Active |
| API | castle-api (FastAPI) | Active |
| Dashboard | castle-app (React, Vite, shadcn/ui) | Active |
| Python packaging | uv | Active |
| Node packaging | pnpm | Active |
| Linting | ruff (Python), ESLint (TS) | Active |
| Type checking | pyright (Python), tsc (TS) | Active |
| Testing | pytest (Python), Vitest (TS) | Active |
| Secrets | `~/.castle/secrets/` file-based | Active |
| Data storage | Filesystem (`/data/castle/`) | Active |
| Messaging | MQTT (Mosquitto) | Planned |
| Node discovery | mDNS/Avahi + MQTT | Planned |
| Rust packaging | cargo | Planned |
| Go packaging | go build | Planned |
