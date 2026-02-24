# Registry

How castle tracks, configures, and manages programs, services, and jobs.
This is the central reference for `castle.yaml` structure and the registry
architecture.

## castle.yaml

The single source of truth. Lives at the repo root. Three top-level sections:

```yaml
gateway:
  port: 9000

programs:
  my-tool:
    description: Does something useful
    source: programs/my-tool
    stack: python-cli
    behavior: tool
    system_dependencies: [pandoc]

services:
  my-service:
    component: my-service
    run:
      runner: python
      program: my-service
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /my-service }
    manage:
      systemd: {}

jobs:
  my-job:
    component: my-tool
    run:
      runner: command
      argv: [my-tool, sync]
    schedule: "0 2 * * *"
    manage:
      systemd: {}
```

### Section semantics

| Section | Purpose | Category |
|---------|---------|----------|
| `programs:` | Software catalog — what exists | tool, frontend, daemon |
| `services:` | Long-running daemons — how they run | service |
| `jobs:` | Scheduled tasks — when they run | job |

Services and jobs can reference a program via `component:` for description
fallthrough and source code linking. They can also exist independently
(e.g., `castle-gateway` runs Caddy — not our software).

## Program blocks

Programs define **what software exists** — identity, source, behavior, builds.

### `behavior` — What role this program plays

```yaml
behavior: daemon    # or: tool, frontend
```

Explicit declaration of how the program is used:
- **daemon** — long-running service (python-fastapi stack)
- **tool** — CLI utility (python-cli stack)
- **frontend** — web UI (react-vite stack)

### `source` — Where the source lives

```yaml
source: programs/my-tool
```

Relative path from repo root to the project directory.

### `stack` — Development toolchain

```yaml
stack: python-fastapi   # or: python-cli, react-vite
```

Stacks define how programs get built, checked, and installed.

### `system_dependencies` — Required system packages

```yaml
system_dependencies: [pandoc, poppler-utils]
```

System packages that must be installed for the program to work. Displayed
in `castle tool list` and the dashboard.

### `version` — Program version

```yaml
version: "1.0.0"
```

Optional version metadata.

### `build` — How to build it

```yaml
build:
  commands:
    - ["pnpm", "build"]
  outputs:
    - dist/
```

Programs with build outputs are typically frontends.

## Service blocks

Services define **how long-running daemons are deployed**.

### `run` — How to start it (required)

Discriminated union on `runner`:

| Runner | Sync | Deploy | Key fields |
|--------|------|--------|------------|
| `python` | `uv sync` | `which(program)` → installed binary | `program`, `args` |
| `command` | *(none)* | `which(argv[0])` → resolved path | `argv` |
| `container` | *(none)* | `docker`/`podman` `run` | `image`, `command`, `ports`, `volumes` |
| `node` | `package_manager install` | `package_manager run script` | `script`, `package_manager` |
| `remote` | *(none)* | *(none — no local process)* | `base_url`, `health_url` |

```yaml
run:
  runner: python
  program: my-service     # name in [project.scripts]
```

### `expose` — What it exposes

```yaml
expose:
  http:
    internal:
      port: 9001            # Required for HTTP services
    health_path: /health     # Used by health polling
```

### `proxy` — How to proxy it

```yaml
proxy:
  caddy:
    path_prefix: /my-service   # Proxied at gateway:9000/my-service/
```

Castle generates a Caddyfile from these entries. Only needed for services
accessible through the gateway.

### `manage` — How to manage it

```yaml
manage:
  systemd: {}
```

Enables `castle service enable/disable` and `castle logs`. An empty `{}`
uses defaults (enable=true, restart=on-failure, restart_sec=2).

Full options:
```yaml
manage:
  systemd:
    description: Custom unit description
    restart: always          # on-failure | always | no
    restart_sec: 2
    no_new_privileges: true
    after: [network.target, castle-other.service]
    wanted_by: [default.target]
    exec_reload: "caddy reload ..."
```

### `defaults` — Default environment

```yaml
defaults:
  env:
    CENTRAL_CONTEXT_URL: http://localhost:9001
    API_KEY: ${secret:MY_API_KEY}
```

Castle resolves `${secret:NAME}` by reading `~/.castle/secrets/NAME`.
Never store secrets in castle.yaml or project directories.

## Job blocks

Jobs define **how scheduled tasks run**. Same blocks as services plus
`schedule` and `timezone`.

### `schedule` — Cron expression (required)

```yaml
schedule: "*/5 * * * *"
timezone: America/Los_Angeles    # default
```

Castle generates a systemd `.timer` file alongside the `.service` unit.

### Other blocks

Jobs also support `run` (required), `manage`, and `defaults` — same
semantics as services.

## Registering a new program

### Via `castle create` (recommended)

```bash
# Service — scaffolds project, assigns port, registers in castle.yaml
castle create my-service --stack python-fastapi --description "Does something"

# Tool — scaffolds under programs/
castle create my-tool --stack python-cli --description "Does something"
```

### Manually

Add entries to the appropriate sections of `castle.yaml`:

```yaml
# Tool — only needs a program entry
programs:
  my-tool:
    description: Does something useful
    source: programs/my-tool
    stack: python-cli
    behavior: tool

# Service — needs both program and service entries
programs:
  my-service:
    description: Does something useful
    source: programs/my-service
    stack: python-fastapi
    behavior: daemon

services:
  my-service:
    component: my-service
    run:
      runner: python
      program: my-service
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /my-service }
    manage:
      systemd: {}
```

## Lifecycle

### Service lifecycle

```bash
castle create my-service --stack python-fastapi   # 1. Scaffold + register
cd programs/my-service && uv sync         # 2. Install deps
# ... implement ...
castle test my-service                    # 3. Run tests
castle service enable my-service          # 4. Generate systemd unit, start
castle gateway reload                     # 5. Update Caddy routes
```

After `service enable`, the service starts automatically on boot and restarts
on failure. Manage with:

```bash
castle logs my-service -f         # Tail logs
castle run my-service             # Run in foreground (for debugging)
castle service disable my-service # Stop and remove systemd unit
```

### Tool lifecycle

```bash
castle create my-tool --stack python-cli        # 1. Scaffold + register
cd programs/my-tool && uv sync           # 2. Install deps
# ... implement ...
castle test my-tool                      # 3. Run tests
uv tool install --editable programs/my-tool/    # 4. Install to PATH
```

### Job lifecycle

Jobs are defined in the `jobs:` section with a `run` spec and `schedule`:

```yaml
jobs:
  my-job:
    description: Runs nightly
    run:
      runner: command
      argv: ["my-job"]
    schedule: "0 2 * * *"
    manage:
      systemd: {}
```

`castle service enable my-job` generates both a `.service` (Type=oneshot)
and a `.timer` file.

## Infrastructure paths

| What | Where |
|------|-------|
| Registry | `castle.yaml` (repo root) |
| Service data | `/data/castle/<name>/` |
| Secrets | `~/.castle/secrets/<NAME>` |
| Generated Caddyfile | `~/.castle/generated/Caddyfile` |
| Systemd units | `~/.config/systemd/user/castle-*.service` |
| Systemd timers | `~/.config/systemd/user/castle-*.timer` |

## Manifest models

The Pydantic models live in `core/src/castle_core/manifest.py`. Key classes:

- `ProgramSpec` — software catalog entry (source, behavior, stack, build, system_dependencies)
- `ServiceSpec` — long-running daemon (run, expose, proxy, manage, defaults)
- `JobSpec` — scheduled task (run, schedule, manage, defaults)
- `RunSpec` — discriminated union (RunPython, RunCommand, RunContainer, RunNode, RunRemote)
- `ExposeSpec`, `ProxySpec`, `ManageSpec`, `BuildSpec`
- `CaddySpec`, `SystemdSpec`, `HttpExposeSpec`, `HttpInternal`

Config loading: `core/src/castle_core/config.py` — `load_config()` parses
castle.yaml into `CastleConfig` with typed `programs`, `services`, and
`jobs` dicts.

Infrastructure generators: `core/src/castle_core/generators/` — systemd unit/timer
generation (`systemd.py`) and Caddyfile generation (`caddyfile.py`).
