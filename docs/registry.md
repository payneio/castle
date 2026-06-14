# Registry

How castle tracks, configures, and manages programs, services, and jobs.
This is the central reference for `castle.yaml` structure and the registry
architecture.

## Vocabulary (canonical)

Use these terms consistently across code, CLI, API, and docs.

- **program** — any project castle manages, regardless of what it does. The
  software catalog (`programs:`). Every program has a **behavior** and an
  optional **stack**. *("component" was the old name for program — don't use it.)*
- **behavior** — what a program *is*: `tool` (a CLI you invoke), `daemon` (a
  long-running server), `frontend` (a web UI). A property of the program,
  independent of whether/how it's deployed.
- **stack** — a creation-time toolchain + scaffold template (`python-cli`,
  `python-fastapi`, `react-vite`). Optional; seeds a program's default dev
  commands but isn't required at runtime.
- **service** — a program deployed as a long-running systemd `.service`
  (`services:`).
- **job** — a program deployed as a scheduled systemd `.timer` (+ oneshot)
  (`jobs:`).
- **deployment** — the umbrella for "a service or a job" (a program materialized
  into the runtime). The registry's deployed entries are deployments.

**Two orthogonal axes.** *behavior* (tool/daemon/frontend) is **what** a program
is; *service/job* is **how/when** it's deployed. They're independent: a program
may have neither (a tool you just install), a **service** (always-on), or a
**job** (scheduled). A `daemon`-behavior program is usually deployed as a
service; a `tool`-behavior program may back a job or just be installed for
manual use.

## castle.yaml

The single source of truth. Lives at `~/.castle/castle.yaml`. Three top-level
sections:

```yaml
gateway:
  port: 9000

programs:
  my-tool:
    description: Does something useful
    source: code/my-tool
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
source: code/my-tool        # your programs, under ~/.castle/code/
source: repo:castle-api      # castle's own programs, inside the git repo
```

The `source` path is resolved one of three ways (`core/src/castle_core/config.py`):

| `source:` value | Resolves to | Used for |
|-----------------|-------------|----------|
| `code/my-tool` *(relative)* | `$CASTLE_HOME/code/my-tool` | Your own programs |
| `repo:castle-api` | `<repo>/castle-api` (via the top-level `repo:` field) | Castle's built-in programs |
| `/abs/path` | as-is | Anything explicitly absolute |

Relative sources resolve against the castle home (`$CASTLE_HOME`, default
`~/.castle` — see [Infrastructure paths](#infrastructure-paths)). Most programs
you create live under **`$CASTLE_HOME/code/`** and are recorded as
`source: code/<name>`. Castle's own programs (CLI, core, castle-api, app) live in
the git repo and use the `repo:` prefix. When `castle deploy` writes `castle.yaml`
back out, it rewrites absolute paths into these relative forms.

### `stack` — Development toolchain (optional)

```yaml
stack: python-fastapi   # or: python-cli, react-vite — OPTIONAL
```

A stack provides **default** dev-verb commands (build/test/lint/type-check/…)
and a scaffold template for new code. It is **optional**: a program with no
stack works fine as long as it declares its own `commands:`. Stacks are a
creation-time convenience, not a runtime requirement.

### `commands` — Per-program dev verbs

```yaml
commands:
  lint:  [["ruff", "check", "."]]
  test:  [["pytest", "tests/"]]
  run:   [["./bin/my-tool", "--serve"]]
```

Each verb is a list of argv lists (run in sequence). A declared verb **overrides**
the stack default; an absent verb falls back to the stack handler (if any), else
the verb is unavailable. `build` is declared via `build:` (it also carries
`outputs:`); every other verb via `commands:`. This is what lets a wired-in repo
with no stack be linted/tested/run. Verb resolution lives in
`core/src/castle_core/stacks.py` (`run_action`, `available_actions`).

### `repo` / `ref` — Wiring in an existing repo

```yaml
repo: https://github.com/me/widget.git
ref: v2.1.0          # optional branch/tag/commit
```

`repo` records a git URL so `castle clone` can provision the source on a fresh
machine. When `source:` points at an existing working copy, that takes
precedence. Use `castle add <path|url>` to register an existing repo as a program.

### `system_dependencies` — Required system packages

```yaml
system_dependencies: [pandoc, poppler-utils]
```

System packages that must be installed for the program to work. Displayed
in `castle list --behavior tool` and the dashboard.

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

## How programs get into `~/.castle/code/`

Every program's source lives in one place — `~/.castle/code/<name>/`. It can
arrive there a few ways:

1. **Scaffold a new one** with `castle create` — writes the project into
   `~/.castle/code/<name>/` and registers it in `castle.yaml` with
   `source: code/<name>`.
2. **Clone an existing project** — `git clone <url> ~/.castle/code/<name>`,
   then add a `programs:` entry pointing at `source: code/<name>`.
3. **Drop files in directly** — a `code/<name>/` directory is just a working
   tree; it doesn't have to be under version control to be registered and run.

`~/.castle/` and `~/.castle/code/` are **not** themselves git repos, and there
are no submodules. Each program directory manages its own version control (or
none) independently — some are standalone git clones, others are just loose
files.

Castle's own programs (CLI, core, castle-api, app) are the exception: they live
inside the castle git repo and are referenced with `source: repo:<name>`.

## Registering a new program

### Via `castle create` (recommended)

```bash
# Service — scaffolds into ~/.castle/code/, assigns port, registers in castle.yaml
castle create my-service --stack python-fastapi --description "Does something"

# Tool — scaffolds into ~/.castle/code/
castle create my-tool --stack python-cli --description "Does something"
```

### Manually

Clone or create the project under `~/.castle/code/`, then add entries to the
appropriate sections of `castle.yaml`:

```yaml
# Tool — only needs a program entry
programs:
  my-tool:
    description: Does something useful
    source: code/my-tool
    stack: python-cli
    behavior: tool

# Service — needs both program and service entries
programs:
  my-service:
    description: Does something useful
    source: code/my-service
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
cd ~/.castle/code/my-service && uv sync   # 2. Install deps
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
cd ~/.castle/code/my-tool && uv sync     # 2. Install deps
# ... implement ...
castle test my-tool                      # 3. Run tests
uv tool install --editable ~/.castle/code/my-tool/   # 4. Install to PATH
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

Castle uses **two** independent roots, each overridable by an environment
variable (both expand `~` and resolve relative paths):

- **`CASTLE_HOME`** — config, code, artifacts, and secrets. Default `~/.castle`.
- **`CASTLE_DATA_DIR`** — program/service data I/O (potentially large; lives on a
  dedicated volume). Default `/data/castle`. Decoupled from `CASTLE_HOME` on
  purpose so bulk data doesn't sit in the home directory.

| What | Where |
|------|-------|
| Castle home | `$CASTLE_HOME` (default `~/.castle`) |
| Registry | `$CASTLE_HOME/castle.yaml` |
| Program source (yours) | `$CASTLE_HOME/code/<name>/` |
| Program source (castle's) | `<repo>/<name>` (via `source: repo:<name>`) |
| Secrets | `$CASTLE_HOME/secrets/<NAME>` |
| Generated Caddyfile | `$CASTLE_HOME/artifacts/specs/Caddyfile` |
| Built frontends | `$CASTLE_HOME/artifacts/content/<name>/` |
| **Service data** | **`$CASTLE_DATA_DIR/<name>/` (default `/data/castle/<name>/`)** |
| Systemd units | `~/.config/systemd/user/castle-*.service` |
| Systemd timers | `~/.config/systemd/user/castle-*.timer` |

Defined in `core/src/castle_core/config.py`: `CASTLE_HOME` (with derived
`CODE_DIR`, `SECRETS_DIR`, `SPECS_DIR`, `CONTENT_DIR`) and the independent
`DATA_DIR` (`CASTLE_DATA_DIR`). `castle deploy` passes each service its data
path via the generated `<PREFIX>_DATA_DIR` env var. Systemd unit/timer paths are
fixed by systemd's user-unit convention.

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
