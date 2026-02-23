# Component Registry

How castle tracks, configures, and manages components. This is the central
reference for `castle.yaml` structure and the registry architecture.

## castle.yaml

The single source of truth for all components. Lives at the repo root.
Three top-level sections:

```yaml
gateway:
  port: 9000

components:
  my-tool:
    description: Does something useful
    source: components/my-tool
    install:
      path: { alias: my-tool }
    tool:
      system_dependencies: [pandoc]

services:
  my-service:
    component: my-service
    run:
      runner: python
      tool: my-service
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
| `components:` | Software catalog — what exists | tool, frontend, component |
| `services:` | Long-running daemons — how they run | service |
| `jobs:` | Scheduled tasks — when they run | job |

Services and jobs can reference a component via `component:` for description
fallthrough and source code linking. They can also exist independently
(e.g., `castle-gateway` runs Caddy — not our software).

## Component blocks

Components define **what software exists** — identity, source, tools, builds.

### `source` — Where the source lives

```yaml
source: components/my-tool
```

Relative path from repo root to the project directory.

### `install` — How to install it

```yaml
install:
  path:
    alias: my-tool       # Command name in PATH
```

Creates a shim so the tool is available system-wide after
`uv tool install --editable .`.

### `tool` — Tool metadata

```yaml
tool:
  version: "1.0.0"
  system_dependencies: [pandoc, poppler-utils]
```

This block provides metadata for `castle tool list` and the dashboard.
It's separate from `install` (which handles PATH registration). The source
directory is set via the top-level `source` field on the component, not here.

### `build` — How to build it

```yaml
build:
  commands:
    - ["pnpm", "build"]
  outputs:
    - dist/
```

Components with build outputs are categorized as **frontends** in the UI.

## Service blocks

Services define **how long-running daemons are deployed**.

### `run` — How to start it (required)

Discriminated union on `runner`:

| Runner | Sync | Deploy | Key fields |
|--------|------|--------|------------|
| `python` | `uv sync` | `which(tool)` → installed binary | `tool`, `args` |
| `command` | *(none)* | `which(argv[0])` → resolved path | `argv` |
| `container` | *(none)* | `podman run` | `image`, `command`, `ports`, `volumes` |
| `node` | `package_manager install` | `package_manager run script` | `script`, `package_manager` |
| `remote` | *(none)* | *(none — no local process)* | `base_url`, `health_url` |

```yaml
run:
  runner: python
  tool: my-service        # name in [project.scripts]
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

## Registering a new component

### Via `castle create` (recommended)

```bash
# Service — scaffolds project, assigns port, registers in castle.yaml
castle create my-service --type service --description "Does something"

# Tool — scaffolds under components/
castle create my-tool --type tool --description "Does something"
```

### Manually

Add entries to the appropriate sections of `castle.yaml`:

```yaml
# Tool — only needs a component entry
components:
  my-tool:
    description: Does something useful
    source: components/my-tool
    install:
      path:
        alias: my-tool

# Service — needs both component and service entries
components:
  my-service:
    description: Does something useful
    source: components/my-service

services:
  my-service:
    component: my-service
    run:
      runner: python
      tool: my-service
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
castle create my-service --type service   # 1. Scaffold + register
cd components/my-service && uv sync       # 2. Install deps
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
castle create my-tool --type tool        # 1. Scaffold + register
cd components/my-tool && uv sync         # 2. Install deps
# ... implement ...
castle test my-tool                      # 3. Run tests
uv tool install --editable components/my-tool/  # 4. Install to PATH
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
| Component registry | `castle.yaml` (repo root) |
| Service data | `/data/castle/<name>/` |
| Secrets | `~/.castle/secrets/<NAME>` |
| Generated Caddyfile | `~/.castle/generated/Caddyfile` |
| Systemd units | `~/.config/systemd/user/castle-*.service` |
| Systemd timers | `~/.config/systemd/user/castle-*.timer` |

## Manifest models

The Pydantic models live in `core/src/castle_core/manifest.py`. Key classes:

- `ComponentSpec` — software catalog entry (source, install, tool, build)
- `ServiceSpec` — long-running daemon (run, expose, proxy, manage, defaults)
- `JobSpec` — scheduled task (run, schedule, manage, defaults)
- `RunSpec` — discriminated union (RunPython, RunCommand, RunContainer, RunNode, RunRemote)
- `ExposeSpec`, `ProxySpec`, `ManageSpec`, `InstallSpec`, `ToolSpec`, `BuildSpec`
- `CaddySpec`, `SystemdSpec`, `HttpExposeSpec`, `HttpInternal`

Config loading: `core/src/castle_core/config.py` — `load_config()` parses
castle.yaml into `CastleConfig` with typed `components`, `services`, and
`jobs` dicts.

Infrastructure generators: `core/src/castle_core/generators/` — systemd unit/timer
generation (`systemd.py`) and Caddyfile generation (`caddyfile.py`).
