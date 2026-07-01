# Registry

How castle tracks, configures, and manages programs and their deployments.
This is the central reference for `castle.yaml` structure and the registry
architecture.

## Vocabulary (canonical)

Use these terms consistently across code, CLI, API, and docs.

- **program** — any project castle manages, regardless of what it does. The
  software catalog (`programs/`). Every program has an optional **stack**.
  *("component" was the old name for program — don't use it.)*
- **stack** — a creation-time toolchain + scaffold template (`python-cli`,
  `python-fastapi`, `react-vite`). Optional; seeds a program's default dev
  commands but isn't required at runtime.
- **deployment** — a program materialized into this node's runtime
  (`deployments/`). Every deployment is discriminated on its **`manager`**.
- **manager** — who supervises or realizes a deployment: `systemd` (a process,
  or with a `schedule` a `.timer`), `caddy` (a gateway static file_server
  route), `path` (a CLI installed on PATH via `uv tool install`), or `none`
  (an external remote reference). The manager is the deployment's stored
  discriminant.
- **launcher** — for `manager: systemd` only, the process-launch mechanism in
  the nested `run:` block: `python` | `command` | `container` | `compose` |
  `node`. Non-systemd managers have no `run:`/launcher.
- **kind** — the human-facing label, **derived** from the manager (+ schedule),
  never stored: systemd+`schedule` → **job**, systemd → **service**, caddy →
  **static**, path → **tool**, none → **reference**. *(kind replaces the old
  `behavior`; the old `frontend` kind is now `static`.)*

**Two orthogonal axes.** *manager* is **who** realizes a deployment; *kind* is
the **derived** label describing what it is. A program may have no deployment (a
program you just develop), a **service** (always-on), a **job** (scheduled), a
**tool** (installed on PATH), or a **static** (a built frontend served by the
gateway). A single `deployments/<name>.yaml` file carries the whole thing.

## Configuration Directory Layout

Castle splits its configuration across a root directory (`~/.castle/` or your config root) instead of a single file:

```
~/.castle/
├── castle.yaml        # Global settings (gateway, repo, etc.)
├── programs/          # Program configuration files (one file per program)
│   └── my-tool.yaml
└── deployments/       # Deployment configuration files (one file per deployment)
    ├── my-service.yaml   #   manager: systemd            → kind: service
    ├── nightly.yaml      #   manager: systemd + schedule → kind: job
    ├── my-tool.yaml      #   manager: path               → kind: tool
    └── my-app.yaml       #   manager: caddy              → kind: static
```

### castle.yaml (Globals)

The core `castle.yaml` contains configuration settings that apply globally to your Castle platform instance:

```yaml
gateway:
  port: 9000
repo: /data/repos/castle
```

### Resource Configuration Files (`programs/`, `deployments/`)

Each resource (a program or a deployment) is configured in its own YAML file named after the resource's unique ID (e.g., `deployments/my-service.yaml` defines the deployment `my-service`).

**programs/my-tool.yaml:**
```yaml
description: Does something useful
source: /data/repos/my-tool
stack: python-cli
system_dependencies: [pandoc]
```

**deployments/my-service.yaml** (a service — `manager: systemd`, no schedule):
```yaml
program: my-service
manager: systemd
run: { launcher: python, program: my-service }
expose:
  http:
    internal: { port: 9001 }
    health_path: /health
proxy: true   # expose at my-service.<gateway.domain>
manage:
  systemd: {}
```

**deployments/nightly.yaml** (a job — `manager: systemd` + `schedule`):
```yaml
program: my-tool
manager: systemd
run: { launcher: command, argv: [my-tool, sync] }
schedule: "0 2 * * *"
manage:
  systemd: {}
```

**deployments/my-tool.yaml** (a tool — `manager: path`, no `run:`):
```yaml
program: my-tool
manager: path
```

**deployments/my-app.yaml** (a static frontend — `manager: caddy`, no `run:`):
```yaml
program: my-app
manager: caddy
root: dist
```

### Resource Categories

| Category | Location | Purpose | Kinds (derived) |
|----------|----------|---------|-----------------|
| **programs** | `programs/*.yaml` | Software catalog — what software exists | — |
| **deployments** | `deployments/*.yaml` | How a program is realized on this node | service, job, tool, static, reference |

A deployment can reference a program via `program:` for description fallthrough
and source code linking. It can also exist independently (e.g., `castle-gateway`
runs Caddy — not our software). The **kind** is derived from `manager` (+
`schedule`), never stored.

## Program blocks

Programs define **what software exists** — identity, source, builds. How a
program is *used* is not a program property: it's decided by its deployment's
`manager` and surfaces as the derived **kind** (service/job/tool/static/reference).
A program with no deployment is just source castle knows how to develop.

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
in `castle tool list` / `castle tool info` and the dashboard.

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

Programs with build outputs are typically served as **static** deployments.

## Deployment blocks

Deployments define **how a program is realized on this node**. Every deployment
declares a **`manager`** — who makes it available and supervises its lifecycle:

### `manager` — Who realizes it (the discriminant)

A deployment is a *managed materialization* of a program. Its **`manager`** is
the stored discriminant — the single axis lifecycle, deploy, and status all
dispatch on:

| Manager | Makes available as | Launch mechanism | start/stop | Kind |
|---------|--------------------|------------------|------------|------|
| **systemd** | a running process (or a `.timer` for jobs) | nested `run: { launcher: … }` | `systemctl` | service / job |
| **caddy** | a gateway static file_server route | *(none — files on disk; `root:`)* | add/remove route + reload | static |
| **path** | an installed CLI on `PATH` | *(none — `uv tool install`)* | `uv tool install` / `uninstall` | tool |
| **none** | an external reference | *(none; `base_url:`/`health_url:`)* | *(nothing — not ours)* | reference |

The **kind** (service/job/tool/static/reference) is **derived** from `manager` (+
`schedule`) — it never drives logic and is never stored. `DeploymentSpec` is a
discriminated union on `manager` (SystemdDeployment/CaddyDeployment/
PathDeployment/RemoteDeployment); see [Manifest models](#manifest-models).

### `run` — How to launch it (systemd only)

For `manager: systemd` **only**, the nested `run:` block carries a **`launcher`**
— the process-launch mechanism. Non-systemd managers have no `run:`/launcher;
their fields live directly on the deployment (caddy has `root:`, none has
`base_url:`/`health_url:`).

Nested launch spec, discriminated union on `launcher`:

| Launcher | Deploy | Key fields |
|----------|--------|------------|
| `python` | `uv run --project <source> --no-dev <program>` | `program`, `args` |
| `command` | `which(argv[0])` → resolved path | `argv` |
| `container` | `docker`/`podman` `run` | `image`, `command`, `ports`, `volumes` |
| `compose` | `docker compose -p <project> -f <file> up` (+ `ExecStop=down`) | `file`, `project_name` |
| `node` | `package_manager run script` | `script`, `package_manager` |

A `python` launcher runs **in place from its own project venv** via `uv run`, which
syncs the env to the project's lockfile before launching. There is no separate
tool venv and no `uv tool install` step: **a restart picks up both code and
dependency changes** (the deploy-time `ExecStart` is deterministic from `source`,
so it never goes stale). `uv tool install` is reserved for `manager: path`
deployments (tools), where being on a human's PATH is the point. If a `python`
launcher declares a `program` with no resolvable `source`, deploy falls back to a
PATH lookup of the script.

```yaml
manager: systemd
run:
  launcher: python
  program: my-service     # name in [project.scripts]
```

A `compose` launcher supervises a **whole multi-container stack as one systemd
unit** — `ExecStart` runs `docker compose … up` attached (`Type=simple`) and a
generated `ExecStop` runs `… down` so networks/anonymous volumes are reclaimed on
stop. Unlike the single-container `container` launcher, compose owns the stack's own
networking, startup ordering, and per-service health — Castle delegates rather
than reinventing orchestration. Secrets/env reach compose through the unit's
`Environment=`/`EnvironmentFile=` (from `defaults.env`), which compose interpolates
from the process environment. This is what runs the shared **Supabase substrate**
(see @docs/stacks/supabase.md).

```yaml
manager: systemd
run:
  launcher: compose
  file: docker-compose.yml   # resolved under the program source
  # project_name: castle-my-stack   # optional; defaults to castle-<name>
```

### `root` — Static frontend (caddy only)

For `manager: caddy`, `root:` names the built-frontend directory (relative to the
program source) that the gateway serves via `file_server`. There is no process
and no `run:` block.

```yaml
manager: caddy
root: dist    # served at <name>.<gateway.domain>
```

### `base_url` / `health_url` — Remote reference (none only)

For `manager: none`, the deployment is an external reference — a service on
another node — with no local process. It carries `base_url:` and `health_url:`
directly.

### `expose` — What it exposes

```yaml
expose:
  http:
    internal:
      port: 9001            # Required for HTTP services
    health_path: /health     # Used by health polling
```

### `proxy` — Expose the service at a subdomain

`proxy` is a **checkbox** (a bool): `true` means the gateway routes
**`<service-name>.<gateway.domain>`** to this service; omitted/`false` means the
service is reachable only at its own `host:port`.

```yaml
proxy: true   # expose at <service-name>.<gateway.domain>
```

### `public` — Also expose to the public internet (opt-in)

`public: true` additionally projects a proxied service to the public internet via a
Cloudflare tunnel, at **`<service-name>.<gateway.public_domain>`** (a separate zone,
so internal subdomain names stay out of public DNS). Defaults to `false` — public is
explicit — and **requires `proxy: true`**. `castle deploy` generates the cloudflared
ingress from the set of public services. Needs `gateway.public_domain` +
`gateway.tunnel_id` set and the `castle-tunnel` service running; see
@docs/tunnel-setup.md for the one-time setup.

```yaml
proxy: true
public: true   # also reachable at <service-name>.<gateway.public_domain>
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
| **proxy** | a local service on a port — Caddy `reverse_proxy localhost:PORT` | a service's `proxy: true` |
| **static** | a built frontend's `dist/` — Caddy `file_server` (no process) | a `manager: caddy` deployment (kind **static**) with a `root:` (served at `<name>.<domain>`) |
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
put a service on HTTPS is to set `proxy: true` (and use acme mode). A node with no public
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

Every subdomain is the **service name**: a service sets `proxy: true` and
is published at `<name>.<domain>`. Services stay domain-agnostic (switching
`gateway.domain` needs no service edits). One `*.<domain>` site means a single cert
covers every route — adding a service needs no new cert.

Setup (the parts castle can't do for you):

- **DNS-plugin Caddy.** Stock Caddy has no DNS modules; build one with the
  provider plugin: `./install.sh --with-dns-plugin=cloudflare` (uses `xcaddy`,
  installs to `/usr/local/bin/caddy`, which the gateway picks up on next deploy).
- **Provider token.** Store a scoped API token as the `CLOUDFLARE_API_TOKEN`
  secret (Cloudflare scope: **Zone → DNS → Edit**), and map it into the gateway
  service env — add to `deployments/castle-gateway.yaml`:
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
| `${public_url}` | the service's gateway-facing base URL — `https://<name>.<domain>` when exposed under `tls: acme`, else the node-local `http://localhost:<port>`. The origin an app allowlists (CORS/WebSocket/secure-context); tracks `gateway.domain`, so a domain change needs no app edit. |
| `${secret:NAME}` | the contents of `~/.castle/secrets/NAME` |

Hardcode the values instead if you prefer; the placeholders just save you from
repeating castle's computed paths/ports. `castle program create` scaffolds the
`${port}`/`${data_dir}` lines for new services. Never store secrets in
castle.yaml — use `${secret:…}`.

## Job fields

A **job** is just a `manager: systemd` deployment that also carries a
`schedule` — the derived kind flips from service to job. Same blocks as a
service (nested `run:` launch, `manage`, `defaults`) plus `schedule` and
`timezone`.

### `schedule` — Cron expression (required for a job)

```yaml
schedule: "*/5 * * * *"
timezone: America/Los_Angeles    # default
```

Castle generates a systemd `.timer` file alongside the `.service` unit.

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

Clone or create the project under `/data/repos/`, then add a `programs/<name>.yaml`
file (plus a `deployments/<name>.yaml` file if it's deployed):

```yaml
# Tool — programs/my-tool.yaml (a program)
description: Does something useful
source: /data/repos/my-tool
stack: python-cli
```
```yaml
# Tool — deployments/my-tool.yaml (installed on PATH → kind: tool)
program: my-tool
manager: path
```

```yaml
# Service — programs/my-service.yaml (a program)
description: Does something useful
source: /data/repos/my-service
stack: python-fastapi
```
```yaml
# Service — deployments/my-service.yaml (manager: systemd → kind: service)
program: my-service
manager: systemd
run:
  launcher: python
  program: my-service
expose:
  http:
    internal: { port: 9001 }
    health_path: /health
proxy: true   # expose at my-service.<gateway.domain>
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

Jobs are deployments with `manager: systemd` plus a `schedule` — a
`deployments/my-job.yaml` file with a nested `run:` launch block:

```yaml
# deployments/my-job.yaml (manager: systemd + schedule → kind: job)
program: my-job
manager: systemd
run:
  launcher: command
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

- `ProgramSpec` — software catalog entry (source, stack, build, system_dependencies)
- `DeploymentSpec` — a deployment, a discriminated union on `manager`:
  `SystemdDeployment` (service/job — run, expose, proxy, schedule, manage,
  defaults), `CaddyDeployment` (static — root), `PathDeployment` (tool),
  `RemoteDeployment` (reference — base_url, health_url)
- `LaunchSpec` — the nested `run:` block (systemd only), a discriminated union on
  `launcher` (LaunchPython, LaunchCommand, LaunchContainer, LaunchCompose, LaunchNode)
- `ExposeSpec`, `ProxySpec`, `ManageSpec`, `BuildSpec`
- `CaddySpec`, `SystemdSpec`, `HttpExposeSpec`, `HttpInternal`

Config loading: `core/src/castle_core/config.py` — `load_config()` parses the
config root into `CastleConfig` with typed `programs` and `deployments` dicts.

Infrastructure generators: `core/src/castle_core/generators/` — systemd unit/timer
generation (`systemd.py`) and Caddyfile generation (`caddyfile.py`).
