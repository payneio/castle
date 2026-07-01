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

## Configuration Directory Layout

Castle splits its configuration across a root directory (`~/.castle/` or your config root) instead of a single file:

```
~/.castle/
├── castle.yaml        # Global settings (gateway, repo, etc.)
├── programs/          # Program configuration files (one file per program)
│   └── my-tool.yaml
├── services/          # Service configuration files (one file per service)
│   └── my-service.yaml
└── jobs/              # Job configuration files (one file per job)
    └── my-job.yaml
```

### castle.yaml (Globals)

The core `castle.yaml` contains configuration settings that apply globally to your Castle platform instance:

```yaml
gateway:
  port: 9000
repo: /data/repos/castle
```

### Resource Configuration Files (`programs/`, `services/`, `jobs/`)

Each resource (program, service, or job) is configured in its own YAML file named after the resource's unique ID (e.g., `services/my-service.yaml` defines the service `my-service`).

**programs/my-tool.yaml:**
```yaml
description: Does something useful
source: /data/repos/my-tool
stack: python-cli
behavior: tool
system_dependencies: [pandoc]
```

**services/my-service.yaml:**
```yaml
program: my-service
run:
  runner: python
  program: my-service
expose:
  http:
    internal: { port: 9001 }
    health_path: /health
proxy:
  caddy: {}   # expose at my-service.<gateway.domain>
manage:
  systemd: {}
```

**jobs/my-job.yaml:**
```yaml
program: my-tool
run:
  runner: command
  argv: [my-tool, sync]
schedule: "0 2 * * *"
manage:
  systemd: {}
```

### Resource Categories

| Category | Location | Purpose | Role / Types |
|----------|----------|---------|--------------|
| **programs** | `programs/*.yaml` | Software catalog — what software exists | tool, frontend, daemon |
| **services** | `services/*.yaml` | Long-running daemons — how they run | service |
| **jobs** | `jobs/*.yaml` | Scheduled tasks — when they run | job |

Services and jobs can reference a program via `program:` for description
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
source: /data/repos/my-tool   # your programs, under $CASTLE_REPOS_DIR
source: repo:castle-api        # castle's own programs, inside the git repo
```

The `source` path is resolved one of three ways (`core/src/castle_core/config.py`):

| `source:` value | Resolves to | Used for |
|-----------------|-------------|----------|
| `/data/repos/my-tool` *(absolute)* | as-is | Your own programs (the default) |
| `repo:castle-api` | `<repo>/castle-api` (via the top-level `repo:` field) | Castle's built-in programs |
| `code/my-tool` *(relative)* | `$CASTLE_HOME/code/my-tool` | Legacy — pre-`/data/repos` layout |

Programs you create or adopt live under **`$CASTLE_REPOS_DIR`** (default
`/data/repos`, override with `CASTLE_REPOS_DIR`) and are recorded with an
**absolute** `source:`. Castle's own programs (CLI, core, castle-api, app) live
in the git repo and use the `repo:` prefix. A relative `source:` still resolves
against `$CASTLE_HOME` for back-compat, but new programs no longer use it.

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

`repo` records a git URL so `castle program clone` can provision the source on a fresh
machine. When `source:` points at an existing working copy, that takes
precedence. Use `castle program add <path|url>` to register an existing repo as a program.

### `system_dependencies` — Required system packages

```yaml
system_dependencies: [pandoc, poppler-utils]
```

System packages that must be installed for the program to work. Displayed
in `castle program list --behavior tool` and the dashboard.

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
| `python` | *(none — `uv run` self-syncs)* | `uv run --project <source> --no-dev <program>` | `program`, `args` |
| `command` | *(none)* | `which(argv[0])` → resolved path | `argv` |
| `container` | *(none)* | `docker`/`podman` `run` | `image`, `command`, `ports`, `volumes` |
| `compose` | *(none)* | `docker compose -p <project> -f <file> up` (+ `ExecStop=down`) | `file`, `project_name` |
| `node` | `package_manager install` | `package_manager run script` | `script`, `package_manager` |
| `remote` | *(none)* | *(none — no local process)* | `base_url`, `health_url` |

A `python` service runs **in place from its own project venv** via `uv run`, which
syncs the env to the project's lockfile before launching. There is no separate
tool venv and no `uv tool install` step: **a restart picks up both code and
dependency changes** (the deploy-time `ExecStart` is deterministic from `source`,
so it never goes stale). `uv tool install` is reserved for `tool`-behavior
programs, where being on a human's PATH is the point. If a `python` service
declares a `program` with no resolvable `source`, deploy falls back to a PATH
lookup of the script.

```yaml
run:
  runner: python
  program: my-service     # name in [project.scripts]
```

A `compose` service supervises a **whole multi-container stack as one systemd
unit** — `ExecStart` runs `docker compose … up` attached (`Type=simple`) and a
generated `ExecStop` runs `… down` so networks/anonymous volumes are reclaimed on
stop. Unlike the single-container `container` runner, compose owns the stack's own
networking, startup ordering, and per-service health — Castle delegates rather
than reinventing orchestration. Secrets/env reach compose through the unit's
`Environment=`/`EnvironmentFile=` (from `defaults.env`), which compose interpolates
from the process environment. This is what runs the shared **Supabase substrate**
(see @docs/stacks/supabase.md).

```yaml
run:
  runner: compose
  file: docker-compose.yml   # resolved under the program source
  # project_name: castle-my-stack   # optional; defaults to castle-<name>
```

### `expose` — What it exposes

```yaml
expose:
  http:
    internal:
      port: 9001            # Required for HTTP services
    health_path: /health     # Used by health polling
```

### `proxy` — Expose the service at a subdomain

`proxy.caddy` is a **checkbox**: present (and `enable: true`, the default) means the
gateway routes **`<service-name>.<gateway.domain>`** to this service; absent means
the service is reachable only at its own `host:port`.

```yaml
proxy:
  caddy: {}   # expose at <service-name>.<gateway.domain>
```

The subdomain is always the service name — there's nothing to customize (rename the
service to change it). There are **no path-prefix routes**: a whole subdomain maps
to the backend root, so root-relative asset URLs and `window.location`-derived
WebSocket URLs just work (the failure mode of the old prefix-stripping `handle_path`
routes is gone). Caddy proxies WebSocket upgrades transparently.

**Gateway routes — one concept, three target kinds.** The gateway maps a public
**address** (always a subdomain host, `<name>.<domain>`) to a **target**:

| Kind | Target | Declared by |
|------|--------|-------------|
| **proxy** | a local service on a port — Caddy `reverse_proxy localhost:PORT` | a service's `proxy.caddy` |
| **static** | a built frontend's `dist/` — Caddy `file_server` (no process) | a `frontend` program with `build.outputs` and **no** service (auto-exposed at `<name>.<domain>`) |
| **remote** | a service on another node | mesh discovery (out of scope of the single-node gateway) |

"Serving a frontend" and "proxying a service" are the same thing — a subdomain
route — differing only in whether the target is files on disk or a live process.
The table is shown by `castle gateway status`, the dashboard Gateway panel, and
`GET /gateway`; the Caddyfile is generated from it.

**The dashboard and its API.** `castle` (the dashboard frontend) and `castle-api`
are just two such subdomains (`castle.<domain>`, `castle-api.<domain>`); the
dashboard calls the API **cross-origin** (castle-api allows CORS `*`). The bare
gateway port (`:9000`) redirects to the dashboard subdomain. On a node with **no
domain** (`gateway.tls: off`), there are no subdomains, so `:9000` serves just the
control plane — the dashboard at `/` plus a `/api` reverse-proxy to castle-api —
and other services stay port-only.

#### Host routes need DNS, and the gateway is HTTP-only

A host route only does something once `<host>` resolves **to this node**. For a
LAN `.lan` zone that's the LAN's DNS authority (typically the router that hands
out `.lan` DHCP names) — not necessarily any central/mesh resolver. A single
dnsmasq wildcard routes every subdomain to the gateway, so each new host-routed
service works with no further DNS edits:

```
address=/<node>.lan/<node-ip>      # e.g. address=/node.lan/192.0.2.10
```

Pin `<node-ip>` with a DHCP reservation — the wildcard hardcodes it.

By default the gateway is **HTTP-only**: it generates `auto_https off` and listens
on a bare `:<gateway-port>` (default `:9000`), so reach it at `http://<host>:9000/`,
**not** `https://` (a TLS hello to the plain-HTTP listener fails with "wrong
version number"). `gateway.tls` has two values:

| `gateway.tls` | listener | host routes | cert / trust |
|---------------|----------|-------------|--------------|
| `off` (default/unset) | `:<port>` HTTP, `auto_https off` | host matcher on `:<port>` | none |
| `acme` | one `*.<domain>` `:443` site | matcher inside the wildcard site | **real Let's Encrypt wildcard, no CA install** |

Path-prefix and static routes always stay on the HTTP `:<port>` site — the way to
put a service on HTTPS is to give it a `proxy.caddy.host`. A node with no public
domain stays on `off` (plain HTTP; use `localhost`/direct ports for anything that
needs a secure context).

HTTPS matters beyond encryption: only `https://` (and `http://localhost`) is a
browser **secure context**, the prerequisite for WebCrypto/`crypto.subtle` — which
apps doing device identity or end-to-end crypto require and browsers disable on
plain-HTTP LAN hosts. That's the reason to move such a service to a host route with
`acme`.

**Bind 443/80.** The `acme` HTTPS site listens on `:443` (and redirects `:80`). A
user-level gateway can't bind privileged ports under `NoNewPrivileges`, so lower
the floor once: `net.ipv4.ip_unprivileged_port_start=80` (persist in
`/etc/sysctl.d/`). This beats `setcap`, which `NoNewPrivileges=true` would void.

#### Publicly-trusted HTTPS — `gateway.tls: acme`

A private-CA approach (Caddy's `tls internal`) forces every client device to trust
a custom root — which some platforms (e.g. Android browsers, and Firefox, which
uses its own store) make painful. `acme` mode avoids it entirely: Caddy obtains a
**real Let's Encrypt wildcard cert** (`*.<domain>`) via a **DNS-01** challenge, so
every browser trusts it with **zero CA install** — while the services stay
**internal-only**.

```yaml
gateway:
  port: 9000
  tls: acme
  domain: example.com          # wildcard cert *.example.com; services → <name>.example.com
  acme_email: you@example.com
  acme_dns_provider: cloudflare   # default
```

```caddyfile
{
    email you@example.com
    acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
}

*.example.com {
    @host_openclaw host openclaw.example.com
    handle @host_openclaw {
        reverse_proxy localhost:18789
    }
}
```

How it stays internal-only: DNS-01 proves domain ownership by having Caddy write a
transient `_acme-challenge` TXT to the **public** zone via the DNS provider API —
it needs **no inbound exposure and no public A records** for the services. Only your
**LAN DNS** resolves `*.<domain>` to the gateway's private IP. (HTTP-01 can't
validate a wildcard, so DNS-01 — and thus the provider token — is mandatory here.)

Every subdomain is the **service name**: a service checks the `proxy.caddy` box and
is published at `<name>.<domain>`. Services stay domain-agnostic (switching
`gateway.domain` needs no service edits). One `*.<domain>` site means a single cert
covers every route — adding a service needs no new cert.

Setup (the parts castle can't do for you):

- **DNS-plugin Caddy.** Stock Caddy has no DNS modules; build one with the
  provider plugin: `./install.sh --with-dns-plugin=cloudflare` (uses `xcaddy`,
  installs to `/usr/local/bin/caddy`, which the gateway picks up on next deploy).
- **Provider token.** Store a scoped API token as the `CLOUDFLARE_API_TOKEN`
  secret (Cloudflare scope: **Zone → DNS → Edit**), and map it into the gateway
  service env — add to `services/castle-gateway.yaml`:
  ```yaml
  defaults:
    env:
      CLOUDFLARE_API_TOKEN: ${secret:CLOUDFLARE_API_TOKEN}
  ```
  `castle deploy` warns if the domain, this env var, or the secret is missing.
- **LAN DNS.** Add a wildcard on your LAN's DNS server (usually the router)
  pointing `*.<domain>` at the gateway's private IP — `address=/<domain>/<gateway-ip>`
  (dnsmasq) or the equivalent A record. The public zone gets no A records, so
  services aren't externally reachable.
- **Staging first.** Set `CASTLE_ACME_STAGING=1` to use Let's Encrypt's staging CA
  (its rate limits are generous) while verifying issuance, then unset it and
  redeploy to get a browser-trusted production cert. Verify with
  `openssl s_client -connect <ip>:443 -servername claw.<domain> | openssl x509 -noout -issuer`.

The 443/80 bind requirement (above) applies here. There's no CA to distribute —
the wildcard is publicly trusted.

Routing only moves bytes — it does **not** supply the proxied app's own auth.
If a backend requires a token/credential (e.g. in the URL or a header), that
stays the client's responsibility through the gateway exactly as it would direct.
A host served over HTTPS also has its own **origin** (`https://foo.lan`, no port);
an app that allowlists origins must include it.

### `manage` — How to manage it

```yaml
manage:
  systemd: {}
```

Enables `castle service enable/disable` and `castle service logs`. An empty `{}`
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

### `defaults` — Environment

`defaults.env` is the **single, explicit source** of the env a service/job runs
with — what you write here is exactly what lands in the systemd unit. Castle
does **not** inject hidden convention vars; whatever env var your program reads
for its port, data dir, etc., you map here.

```yaml
expose: { http: { internal: { port: 9001 }, health_path: /health } }
defaults:
  env:
    MY_SERVICE_PORT: ${port}          # the program's own port var ← expose.port
    MY_SERVICE_DATA_DIR: ${data_dir}  # = $CASTLE_DATA_DIR/<name>
    CENTRAL_CONTEXT_URL: http://localhost:9001
    API_KEY: ${secret:MY_API_KEY}
```

Values may contain placeholders that castle resolves at deploy:

| Placeholder | Expands to |
|-------------|------------|
| `${port}` | the service's `expose.http.internal.port` (so it can't drift) |
| `${data_dir}` | `$CASTLE_DATA_DIR/<program-or-name>` (the dedicated data volume) |
| `${name}` | the deployment name |
| `${secret:NAME}` | the contents of `~/.castle/secrets/NAME` |

Hardcode the values instead if you prefer; the placeholders just save you from
repeating castle's computed paths/ports. `castle program create` scaffolds the
`${port}`/`${data_dir}` lines for new services. Never store secrets in
castle.yaml — use `${secret:…}`.

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

## How programs get into `/data/repos/`

Every program's source lives under `$CASTLE_REPOS_DIR` (default `/data/repos/<name>/`).
It can arrive there a few ways:

1. **Scaffold a new one** with `castle program create` — writes the project into
   `/data/repos/<name>/` and registers it in `castle.yaml` with an absolute
   `source: /data/repos/<name>`.
2. **Adopt an existing repo** — `castle program add <path|git-url>` registers it
   in place (or records its `repo:` URL for `castle program clone`).
3. **Drop files in directly** — a `/data/repos/<name>/` directory is just a
   working tree; it doesn't have to be under version control to be run.

`/data/repos/` holds independent repos — each program directory manages its own
version control (or none); some are standalone git clones, others loose files.

Castle's own programs (CLI, core, castle-api, app) are the exception: they live
inside the castle git repo and are referenced with `source: repo:<name>`.

## Registering a new program

### Via `castle program create` (recommended)

```bash
# Service — scaffolds into /data/repos/, assigns port, registers in castle.yaml
castle program create my-service --stack python-fastapi --description "Does something"

# Tool — scaffolds into /data/repos/
castle program create my-tool --stack python-cli --description "Does something"
```

### Manually

Clone or create the project under `/data/repos/`, then add entries to the
appropriate sections of `castle.yaml`:

```yaml
# Tool — only needs a program entry
programs:
  my-tool:
    description: Does something useful
    source: /data/repos/my-tool
    stack: python-cli
    behavior: tool

# Service — needs both program and service entries
programs:
  my-service:
    description: Does something useful
    source: /data/repos/my-service
    stack: python-fastapi
    behavior: daemon

services:
  my-service:
    program: my-service
    run:
      runner: python
      program: my-service
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: {}   # expose at my-service.<gateway.domain>
    manage:
      systemd: {}
```

## Lifecycle

### Service lifecycle

```bash
castle program create my-service --stack python-fastapi   # 1. Scaffold + register
cd /data/repos/my-service && uv sync   # 2. Install deps
# ... implement ...
castle program test my-service                    # 3. Run tests
castle service enable my-service          # 4. Generate systemd unit, start
castle gateway reload                     # 5. Update Caddy routes
```

After `service enable`, the service starts automatically on boot and restarts
on failure. Manage with:

```bash
castle logs my-service -f         # Tail logs
castle service run my-service     # Run in foreground (for debugging)
castle service disable my-service # Stop and remove systemd unit
```

### Tool lifecycle

```bash
castle program create my-tool --stack python-cli        # 1. Scaffold + register
cd /data/repos/my-tool && uv sync     # 2. Install deps
# ... implement ...
castle program test my-tool                      # 3. Run tests
uv tool install --editable /data/repos/my-tool/   # 4. Install to PATH
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

`castle job enable my-job` generates both a `.service` (Type=oneshot)
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
| Built frontends | served in place from `<source>/<dist>/` (no copy) |
| **Service data** | **`$CASTLE_DATA_DIR/<name>/` (default `/data/castle/<name>/`)** |
| Systemd units | `~/.config/systemd/user/castle-*.service` |
| Systemd timers | `~/.config/systemd/user/castle-*.timer` |

Defined in `core/src/castle_core/config.py`: `CASTLE_HOME` (with derived
`CODE_DIR`, `SECRETS_DIR`, `SPECS_DIR`, `CONTENT_DIR`) and the independent
`DATA_DIR` (`CASTLE_DATA_DIR`). A service reaches its data path by mapping
`${data_dir}` (= `$CASTLE_DATA_DIR/<name>`) to the env var its program reads, in
`defaults.env`. Systemd unit/timer paths are fixed by systemd's user-unit
convention.

## Manifest models

The Pydantic models live in `core/src/castle_core/manifest.py`. Key classes:

- `ProgramSpec` — software catalog entry (source, behavior, stack, build, system_dependencies)
- `ServiceSpec` — long-running daemon (run, expose, proxy, manage, defaults)
- `JobSpec` — scheduled task (run, schedule, manage, defaults)
- `RunSpec` — discriminated union (RunPython, RunCommand, RunContainer, RunCompose, RunNode, RunRemote)
- `ExposeSpec`, `ProxySpec`, `ManageSpec`, `BuildSpec`
- `CaddySpec`, `SystemdSpec`, `HttpExposeSpec`, `HttpInternal`

Config loading: `core/src/castle_core/config.py` — `load_config()` parses
castle.yaml into `CastleConfig` with typed `programs`, `services`, and
`jobs` dicts.

Infrastructure generators: `core/src/castle_core/generators/` — systemd unit/timer
generation (`systemd.py`) and Caddyfile generation (`caddyfile.py`).
