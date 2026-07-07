# AGENTS.md — Castle

You are working in **Castle**, a personal software platform. Castle is a
monorepo of independent programs managed by the `castle` CLI. From this directory
you can **manage all the software on this box from source** — create programs,
deploy them as services, jobs, tools, or static frontends, route them through the
gateway, expose them over TLS or a public tunnel, and coordinate across nodes.

This file is the canonical, agent-agnostic guide. For exhaustive detail every
section links to a doc under `docs/`. Read those before non-trivial changes.

---

## 1. Mental model — two layers

Castle splits every piece of software into **what it is** and **how it runs here**:

- **`programs/<name>.yaml`** — the software *catalog*: source, stack, build,
  system dependencies. "What software exists."
- **`deployments/<name>.yaml`** — how a program is *realized on this node*.
  Discriminated on **`manager`**: `systemd` | `caddy` | `path` | `none`.

The human-facing **kind** is **derived** from the manager (+ `schedule`), never
stored:

| manager | + schedule? | derived **kind** | what it is |
|---------|-------------|------------------|------------|
| `systemd` | no | **service** | a long-running daemon |
| `systemd` | yes | **job** | a scheduled task (`.timer`) |
| `path` | — | **tool** | a CLI installed on your `PATH` |
| `caddy` | — | **static** | a built frontend served by the gateway |
| `none` | — | **reference** | an external service on another node |

A program may have **no** deployment (just source you develop), or one/more
deployments. Global settings live in **`castle.yaml`** (`gateway`, `repo`,
`agents`). Config root defaults to `~/.castle/`.

**Prime directive:** regular programs must **never depend on castle**. They take
standard config (data dir, port, URLs) via **env vars**; only castle's own
programs (CLI, gateway, api) know castle internals. When you scaffold or adopt a
program, wire it with env vars — not castle imports.

→ Full reference: **`docs/registry.md`** (castle.yaml structure, every field,
manifest models, lifecycle). Architecture rationale: **`docs/design.md`**.

---

## 2. The `castle` CLI

Resource-first: operations live under the resource they act on. Names can collide
across resource types, so the resource is explicit.

```bash
# Programs — the software catalog
castle program list [--kind service] [--stack python-cli] [--json]
castle program info <name> [--json]
castle program create <name> [--stack ...] [--description ...]   # scaffold NEW code
castle program add <path|git-url> [--name ...]                   # adopt EXISTING repo
castle program clone [name]                                      # provision repo: source
castle program delete <name> [--source] [-y]
castle program run <name> [args...]                              # declared run command
castle program build|test|lint|format|type-check|check [name]    # dev verbs

# Services — daemons (manager: systemd, no schedule)
castle service list|info <name> [--json]
castle service create <name> [--program P] [--port N] [--health ...] [--launcher ...]
castle service restart <name>             # imperative bounce
castle service logs <name> [-f] [-n 50]

# Jobs — scheduled tasks (manager: systemd + schedule). create takes --schedule
castle job create <name> [--program P] --schedule "0 2 * * *" [--launcher ...]
castle job <list|info|delete|restart|logs> ...

# Tools — CLIs on PATH (manager: path)
castle tool list [--json]          # each tool's executable + description + install state
castle tool info <name> [--json]

# Platform-wide
castle apply [name] [--plan]                       # converge runtime to config — the workhorse
castle list [--kind ...] [--stack ...] [--json]    # all deployments
castle status                                      # unified health/status
castle doctor                                      # diagnose setup + runtime, with fix hints
castle restart [name]                              # imperative bounce (one or all)
castle gateway                                     # gateway status + route table (inspection)
```

`castle service`/`job`/`tool` are **views** over the one deployment set, filtered
by derived kind. Lifecycle is **convergence**: edit config, then **`castle apply`**
renders units + the Caddyfile and reconciles the runtime (activate what's enabled,
restart what changed, deactivate what's disabled). To durably turn a deployment
off, set `enabled: false` and apply — there is no separate start/stop/enable.
`castle restart` is the one imperative bounce.

**Dev verbs resolve per-program:** a declared `commands:` entry (or `build:`)
overrides the program's stack default, else the stack handler, else the verb is
unavailable — so a wired-in repo with **no stack** works if it declares its
commands. All projects use **uv** (Python) / **pnpm** (frontends).

---

## 3. Recipes

### Create a new service (HTTP daemon)

```bash
castle program create my-service --stack python-fastapi --description "Does X"
cd /data/repos/my-service && uv sync         # implement it
castle program test my-service
castle service create my-service --program my-service --port 9001
castle apply my-service        # renders the unit + gateway route and starts it
```

The service reads its port/data dir from env vars that `deployments/my-service.yaml`
maps via placeholders (see §6). Stack guide: **`docs/stacks/python-fastapi.md`**.

### Create a CLI tool

```bash
castle program create my-tool --stack python-cli --description "Does Y"
cd /data/repos/my-tool && uv sync
castle apply my-tool                 # installs the path deployment on PATH
```

`castle tool list --json` is the machine-readable tool catalog (each tool's real
**executable**, which may differ from the program name). Stack:
**`docs/stacks/python-cli.md`**.

### Create a scheduled job

A job is a `manager: systemd` deployment with a `schedule` (cron). Generates a
`.service` (Type=oneshot) + a `.timer`.

```bash
castle job create nightly --program my-tool --schedule "0 2 * * *" --launcher command
castle apply nightly
```

### Create a static frontend

```bash
# scaffold a Vite/React app under /data/repos/my-frontend (see docs/stacks/react-vite.md)
castle program build my-frontend                      # produces dist/
# deployments/my-frontend.yaml → manager: caddy, root: dist
castle apply                # served at my-frontend.<domain>
```

The gateway serves the build **in place** from `<source>/<root>` — no copy, no
Node process. Stack: **`docs/stacks/react-vite.md`**. Database-backed apps on the
shared Supabase substrate: **`docs/stacks/supabase.md`**.

### Adopt an existing repo (no stack needed)

```bash
castle program add ~/projects/some-rust-tool        # local path
castle program add https://github.com/me/widget.git --name widget
```

Castle detects dev-verb commands (pyproject→uv/ruff/pytest, Cargo.toml→cargo, …)
or you declare them under `commands:` in `programs/<name>.yaml`.

---

## 4. The gateway — routing & exposure

The **Caddy gateway** (port 9000) is the single ingress. It's both a reverse
proxy (to local services) and a static file server (for built frontends). It maps
a public **address** (always a subdomain, `<name>.<domain>`) to a **target**:

| target kind | is | declared by |
|-------------|----|-------------|
| **proxy** | a local service on a port | a service's `proxy: true` |
| **static** | a built frontend's `dist/` | a `manager: caddy` deployment's `root:` |
| **remote** | a service on another node | mesh discovery |

Exposure is a **checkbox** on a service:

```yaml
proxy: true    # expose at <service-name>.<gateway.domain>
public: true   # ALSO expose to the internet via Cloudflare tunnel (requires proxy)
```

- `proxy: false`/omitted → reachable only at its own `host:port`.
- The subdomain is always the **service name** (rename the service to change it).
- There are **no path-prefix routes** — a whole subdomain maps to the backend
  root, so root-relative assets and `window.location` WebSocket URLs just work.

Inspect routes: `castle gateway` / `GET /gateway`. Regenerate routes + reload the
gateway: `castle apply` (converge). → Field-level detail: **`docs/registry.md`**.

---

## 5. DNS & TLS — making names resolve and be trusted

Two orthogonal questions for `https://foo.<domain>/` to work from a LAN browser:
**resolve** (DNS) and **trust** (TLS). Castle doesn't run DNS — you add one
**wildcard** record on the LAN's DNS server (usually the router):
`address=/<domain>/<node-ip>` (dnsmasq) pinned with a DHCP reservation.

`gateway.tls` in `castle.yaml` picks the trust mode:

| `gateway.tls` | serves | client setup | when |
|---------------|--------|--------------|------|
| `off` *(default)* | plain HTTP on `:9000` | none | no HTTPS needed / no domain |
| `acme` | **real Let's Encrypt wildcard** `*.<domain>` via DNS-01 | **nothing** | you own a domain; any device |

`acme` gets a publicly-trusted cert with **no CA to install**, while services stay
**internal-only** (DNS-01 writes a TXT to the public zone; only LAN DNS resolves
the names — the public zone has no A records). HTTPS also unlocks **secure
context** (`crypto.subtle`, service workers), which plain-HTTP LAN hosts lack.

`acme` operational prerequisites (castle can't do these for you):
- **DNS-plugin Caddy** at `/usr/local/bin/caddy` — `./install.sh --with-dns-plugin=cloudflare`.
- **Provider token** stored as a secret and mapped into the gateway service env
  (`CLOUDFLARE_API_TOKEN`); `castle apply` warns if missing.
- **Bind :443/:80** — lower the floor once: `net.ipv4.ip_unprivileged_port_start=80`
  in `/etc/sysctl.d/` (beats `setcap`, which `NoNewPrivileges` would void).
- **Stage first**: `CASTLE_ACME_STAGING=1` at deploy, verify issuance, then unset
  and redeploy for a production cert.

→ Full conceptual + step-by-step guide: **`docs/dns-and-tls.md`**. Read the actual
values for *this* node in `~/.castle/castle.yaml` (`gateway.domain`, `tls`, etc.).

---

## 6. Environment, secrets, data, placeholders

`defaults.env` in a deployment is the **single explicit source** of the env a
service/job runs with — castle injects nothing implicitly. Map the vars your
program reads to castle's computed values with placeholders:

```yaml
expose: { http: { internal: { port: 9001 }, health_path: /health } }
defaults:
  env:
    MY_SERVICE_PORT: ${port}          # = expose.http.internal.port
    MY_SERVICE_DATA_DIR: ${data_dir}  # = $CASTLE_DATA_DIR/<name>
    PUBLIC_URL: ${public_url}          # gateway origin (CORS/allowlists)
    API_KEY: ${secret:MY_API_KEY}      # reads ~/.castle/secrets/MY_API_KEY
```

| placeholder | expands to |
|-------------|-----------|
| `${port}` | the service's `expose.http.internal.port` |
| `${data_dir}` | `$CASTLE_DATA_DIR/<name>` (default `/data/castle/<name>`) |
| `${name}` | the deployment name |
| `${public_url}` | `https://<name>.<domain>` under acme, else `http://localhost:<port>` |
| `${secret:NAME}` | contents of `~/.castle/secrets/NAME` (mode 700) |

**Never** put secrets in `castle.yaml` or project dirs — use `${secret:…}`.
Roots: **`CASTLE_HOME`** (config/code/artifacts/secrets, default `~/.castle`,
env-only — it *contains* castle.yaml) and **program data** (base of `${data_dir}`,
default `/data/castle`) + **repos** (default `/data/repos`). The latter two resolve
**env > `castle.yaml` > default** — set `data_dir:` / `repos_dir:` in `castle.yaml`
(the single source of truth both the CLI and the api read), not a per-shell env var
that only one of them sees. → **`docs/registry.md`** (castle.yaml globals).

---

## 7. Public exposure — Cloudflare tunnel

`public: true` (requires `proxy: true`) projects a service to the internet at
`<name>.<gateway.public_domain>` (a **separate** zone, so internal subdomain names
stay out of public DNS). `castle apply` generates the cloudflared ingress from the
set of public services. Needs `gateway.public_domain` + `gateway.tunnel_id` set and
the `castle-tunnel` service running. → One-time setup: **`docs/tunnel-setup.md`**.

Routing only moves bytes — it does **not** supply a backend's own auth. Do not make
a service public unless it authenticates or is meant to be open.

---

## 8. Mesh — multi-node coordination (opt-in)

Runs on **NATS JetStream** (`castle-nats`, TLS + token). Enable via env on
`castle-api`: `CASTLE_API_NATS_ENABLED=true`, `CASTLE_API_NATS_URL=tls://castle-nats.<domain>:4222`,
`CASTLE_API_NATS_TOKEN=${secret:NATS_TOKEN}`. Each node publishes its
(secret-stripped) registry to a JetStream **KV** bucket, renews a **presence**
key, and watches for peers; remote deployments surface as `manager: none`
**reference** kinds. A static **`role`** (`authority`|`follower`, in `castle.yaml`)
gates who may write the shared-config bucket. A consumed cross-node service
(`requires: - ref: X` satisfied by a peer) is routed by the gateway with a
presence-gated circuit-breaker.

Inspect + drive from the CLI: **`castle mesh status`** / **`castle mesh nodes`** /
**`castle mesh config list|get|set`** (or `GET /mesh/status`, `/nodes`,
`/mesh/config`). Modules: `castle_api.nats_client`, `.mesh`, `.mesh_gateway`,
`.mdns`; secrets via `core` `secret_backends` (file default, OpenBao opt-in).
→ Full history + operations: **`docs/fleet-mesh-plan.md`**.

---

## 9. Where to read more

| Topic | Doc |
|-------|-----|
| Registry model, `castle.yaml`, every field, lifecycle | **`docs/registry.md`** |
| Why castle is shaped this way | **`docs/design.md`** |
| DNS resolution + the two TLS modes, acme recipe | **`docs/dns-and-tls.md`** |
| Public exposure (cloudflared) one-time setup | **`docs/tunnel-setup.md`** |
| Writing FastAPI services | **`docs/stacks/python-fastapi.md`** |
| Writing CLI tools | **`docs/stacks/python-cli.md`** |
| Writing React/Vite frontends | **`docs/stacks/react-vite.md`** |
| Database-backed apps (shared Supabase) | **`docs/stacks/supabase.md`** |
| **Developing Castle itself** (CLI/core/api/app, key files, endpoints) | **`docs/developing-castle.md`** |

Castle's own programs live in this repo (`source: repo:<name>` → cli, core,
castle-api, app). Your programs live under `/data/repos/<name>/` with an absolute
`source:`. When in doubt about *this* node's actual config, read
`~/.castle/castle.yaml` and `castle status`.
