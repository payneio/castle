# Component Registry

How castle tracks, configures, and manages components. This is the central
reference for `castle.yaml` structure and the manifest architecture.

## castle.yaml

The single source of truth for all components. Lives at the repo root.

```yaml
gateway:
  port: 9000

components:
  my-service:
    description: Does something useful
    run:
      runner: python_uv_tool
      tool: my-service
      cwd: my-service
      env:
        MY_SERVICE_DATA_DIR: /data/castle/my-service
        MY_SERVICE_PORT: "9001"
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /my-service }
    manage:
      systemd: {}
```

## Manifest blocks

Each component declares **what it does** through these optional blocks:

### `run` — How to start it

Discriminated union on `runner`:

| Runner | Use case | Key fields |
|--------|----------|------------|
| `python_uv_tool` | Python service/tool via uv | `tool`, `cwd`, `env` |
| `command` | Shell command | `argv`, `cwd`, `env` |
| `python_module` | Python -m invocation | `module`, `args`, `python` |
| `container` | Docker/Podman | `image`, `command`, `ports`, `volumes` |
| `node` | Node.js script | `script`, `package_manager` (npm/pnpm/yarn) |
| `remote` | External service | `base_url`, `health_url` |

**Services** use `python_uv_tool`:
```yaml
run:
  runner: python_uv_tool
  tool: my-service        # name in [project.scripts]
  cwd: my-service         # working directory relative to repo root
  env:
    MY_SERVICE_DATA_DIR: /data/castle/my-service
    MY_SERVICE_PORT: "9001"
```

**Tools invoked by castle** (jobs, scheduled tasks) use `command`:
```yaml
run:
  runner: command
  argv: ["protonmail", "sync"]
  cwd: protonmail
  env:
    PROTONMAIL_USERNAME: user@example.com
```

**Standalone tools** that users invoke directly often have no `run` block at
all — castle just installs them to PATH.

### `expose` — What it exposes

```yaml
expose:
  http:
    internal:
      port: 9001            # Required for services
    health_path: /health     # Used by health polling
```

Having `expose.http` gives the component the **service** role.

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
uses defaults (enable=true, restart=on-failure, restart_sec=5).

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
```

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
  source: components/my-tool/     # Source directory
  version: "1.0.0"
  system_dependencies: [pandoc, poppler-utils]
```

This block provides metadata for `castle tool list` and the dashboard.
It's separate from `install` (which handles PATH registration) and `run`
(which handles execution).

The install method (uv tool install vs symlink) is inferred from the source
directory: if `pyproject.toml` exists, it's a Python package; if the source
is a file, it's symlinked.

### `build` — How to build it

```yaml
build:
  commands:
    - ["pnpm", "build"]
  outputs:
    - dist/
```

Having build outputs gives the component the **frontend** role.

### `triggers` — What triggers it

```yaml
triggers:
  - type: schedule
    cron: "*/5 * * * *"
    timezone: America/Los_Angeles    # default
```

Having a schedule trigger gives the component the **job** role.
Castle generates a systemd .timer file alongside the .service unit.

Other trigger types: `manual`, `event` (source + topic), `request` (protocol).

### `env` with secrets

Environment variables can reference secrets stored in `~/.castle/secrets/`:

```yaml
run:
  env:
    API_KEY: ${secret:MY_API_KEY}
```

Castle resolves `${secret:NAME}` by reading `~/.castle/secrets/NAME`.
Never store secrets in castle.yaml or project directories.

## Role derivation

Roles are **computed** from manifest declarations, never set manually:

| Role | Derived when |
|------|-------------|
| **service** | Has `expose.http` |
| **tool** | Has `install.path` or has `tool` spec (fallback) |
| **worker** | Has `manage.systemd` but no `expose.http` |
| **job** | Has trigger with `type: schedule` |
| **frontend** | Has `build` with outputs or commands |
| **containerized** | Runner is `container` |
| **remote** | Runner is `remote` |

A component can have multiple roles. For example, `protonmail` is both a
**tool** (installed to PATH) and a **job** (runs on a cron schedule).

## Registering a new component

### Via `castle create` (recommended)

```bash
# Service — scaffolds project, assigns port, registers in castle.yaml
castle create my-service --type service --description "Does something"

# Tool — scaffolds under components/
castle create my-tool --type tool --description "Does something"
```

### Manually

Add an entry to the `components:` section of `castle.yaml`:

```yaml
components:
  my-tool:
    description: Does something useful
    tool:
      source: components/my-tool/
    install:
      path:
        alias: my-tool
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

Jobs are tools or services with a schedule trigger. They need both `run`
(so castle knows how to execute them) and `manage.systemd` (so systemd
handles the timer):

```yaml
my-job:
  description: Runs nightly
  run:
    runner: command
    argv: ["my-job"]
  triggers:
    - type: schedule
      cron: "0 2 * * *"
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

- `ComponentManifest` — top-level model, has `roles` computed property
- `RunSpec` — discriminated union (RunPythonUvTool, RunCommand, etc.)
- `TriggerSpec` — union (TriggerSchedule, TriggerManual, TriggerEvent, TriggerRequest)
- `ExposeSpec`, `ProxySpec`, `ManageSpec`, `InstallSpec`, `ToolSpec`, `BuildSpec`
- `CaddySpec`, `SystemdSpec`, `HttpExposeSpec`, `HttpInternal`

Config loading: `core/src/castle_core/config.py` — `load_config()` parses
castle.yaml into `CastleConfig` with typed `components` dict.

Infrastructure generators: `core/src/castle_core/generators/` — systemd unit/timer
generation (`systemd.py`) and Caddyfile generation (`caddyfile.py`).
