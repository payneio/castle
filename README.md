# Castle

> Standing to author, run, govern, and maintain your own software.

A personal software platform. Castle manages independent services, tools, and
frontends — and launches your coding agents — from a single CLI, with a unified
gateway, systemd integration, and a web dashboard.

Historically, applications have usually been developed by third parties, packaged
for distribution, installed through app stores or package managers, and updated
through channels controlled by someone other than the user. That model still works
for large applications, but it is often too heavy for the small, personal,
situational software people increasingly want to create.

AI-assisted development changes the shape of this problem. Users can now create
useful software directly: small services, scripts, dashboards, agents, automations,
and configurations of existing tools. Many of these programs do not need a public
release process, an app store listing, or a conventional distribution channel. They
need a reliable place to run.

Castle provides that place.

Castle gives simple applications a consistent local environment for development,
registration, deployment, discovery, and operation. Programs remain independent, but
Castle provides the surrounding structure: process management, routing, metadata,
service lifecycle, logs, and a common interface for running and inspecting the
software in your domain.

In this sense, Castle is a **personal software estate**: a practical way to organize
the software you create and run yourself, without requiring every tool to become a
fully packaged product.

## How it works

Castle separates *what software exists* from *how it runs*:

- **Programs** — the catalog. A program is a source repo Castle knows how to work
  with (dev verbs, build) and where it lives. One file per program under
  `~/.castle/programs/<name>.yaml`.
- **Deployments** — how a program is realized on this node. One file per deployment
  under `~/.castle/deployments/<name>.yaml`, discriminated by its **manager**:

  | manager | what it is | derived **kind** |
  |---------|------------|------------------|
  | `systemd` | a supervised process — or, with a `schedule`, a timer | **service** / **job** |
  | `caddy` | a static site served by the gateway from a build dir | **static** |
  | `path` | a CLI installed on your PATH (`uv tool install`) | **tool** |
  | `none` | an external service on another node (reference only) | **reference** |

  For `systemd`, a nested `run.launcher` (`python` / `command` / `container` /
  `compose` / `node`) says *how* the process starts. The **kind** is always
  *derived* from the manager (+ `schedule`) — never stored.

A program can have several deployments — a CLI that is both a `tool` on PATH and a
scheduled `job` — so a program has no single kind of its own; it *has deployments*,
each with its own.

Standing everything up is the two honest steps `castle deploy` (regenerate systemd
units and gateway config from your config) then `castle start` (enable/start it).
There is no bundled "up".

## Stacks

Castle **stacks** are pre-configured development environments that provide starting
points for building Castle programs. A stack can define the language, framework,
dependencies, tools, conventions, and Castle integration needed for a particular
kind of application — `python-fastapi`, `python-cli`, `react-vite`, `supabase`.

Stacks are designed to work well with coding assistants. They give assistants a
consistent target when generating Castle programs, making it easier to produce
applications that are correctly structured, configured, and ready to run under
Castle. If your coding assistant understands Castle, it can help you create,
register, manage, and evolve custom applications more efficiently.

A stack seeds a new program's scaffold and default dev-verb commands, but it's
optional at runtime: a program stands on its own via its declared `commands:` and
`source:`, so you can adopt any existing repo with `castle program add` — no stack
required.

## Agents

Castle can launch your coding agents. Declare them in `castle.yaml` under `agents:`
— each entry is just a command Castle runs in a terminal:

```yaml
agents:
  claude:
    command: claude
    description: Anthropic Claude Code
  aider:
    command: aider
    args: ["--no-auto-commits"]
    cwd: /data/repos/my-project
```

The dashboard has a terminal dock that launches any declared agent in a
pseudo-terminal (over a WebSocket) and manages live sessions (list, resume, kill).
Castle is **assistant-agnostic** — it only ever runs `command args` in a pty and
never parses the agent's output, so any interactive CLI works. With no `agents:`
block set, a sensible default set (`claude`, `opencode`, `amplifier`, …) is offered.

## Quick start

**Prerequisites:** a Debian/Ubuntu-family Linux with `apt` and `sudo`, `systemd`
(user services), and `git`. `install.sh` sets up everything else — Docker, Caddy,
`uv`, and the `castle` CLI itself.

```bash
git clone <this-repo> ~/castle && cd ~/castle

# One command: installs uv + the castle CLI, sets up infra (Docker, Caddy, MQTT,
# Postgres), creates ~/.castle, registers Castle's own control plane, builds the UI.
./install.sh

castle deploy && castle start   # apply config to the runtime, then bring it up
castle doctor                   # verify — every check should be green
open http://localhost:9000      # the dashboard
```

`castle doctor` is your friend at every step: it inspects setup *and* runtime and,
for anything not green, prints the exact next command. Run it any time something
looks off — after an install, a deploy, or a config change.

### Exposure: from localhost to your own HTTPS domain

Localhost is the first rung; you climb only as far as you need. Each rung is a small
config change plus `castle deploy`, and `castle doctor` tells you what a rung still
needs.

| Rung | You get | What it takes |
|------|---------|---------------|
| **localhost** *(default)* | dashboard + services on `:9000` / `host:port` | nothing — this is the quick start above |
| **LAN HTTPS** | real `https://<name>.<your-domain>` on every device on your network, publicly-trusted cert, services stay internal | own a domain; set `gateway.tls: acme` + `domain:`; one wildcard DNS record on your router; a Cloudflare token. → [docs/dns-and-tls.md](docs/dns-and-tls.md) |
| **Public** | a chosen service reachable from the internet | `public: true` on the service + a Cloudflare tunnel. → [docs/tunnel-setup.md](docs/tunnel-setup.md) |

The jump to LAN HTTPS is the involved one (DNS + a token + binding `:443`). Set
`gateway.tls: acme` and run `castle doctor` — it enumerates exactly the pieces that
are still missing, each with its fix.

## Creating programs

`castle program create` scaffolds the source **and** its deployment from a stack:

```bash
# A service — FastAPI app + a systemd service deployment (health, unit, route)
castle program create my-api --stack python-fastapi --description "Does something"
castle program test my-api
castle deploy my-api && castle service enable my-api

# A tool — a CLI installed on your PATH
castle program create my-tool --stack python-cli --description "Does something"
castle tool install my-tool

# A static frontend — built once, served by the gateway
castle program create my-app --stack react-vite --description "Web interface"
castle program build my-app && castle deploy

# Adopt an existing repo (no stack needed — dev verbs detected or declared)
castle program add ~/projects/some-rust-tool
```

## CLI

Operations live under the resource they act on. `program` is the catalog;
`service`, `job`, and `tool` are **views** over the one deployment set; platform
lifecycle is top-level.

```
# Programs — the software catalog
castle program list|info|create|add|clone|delete|run|install|uninstall
castle program build|test|lint|type-check|check [name]        # dev verbs

# Deployment lenses (service = systemd, job = systemd + schedule, tool = path)
castle service  list|info|create|delete|deploy|enable|disable|start|stop|restart|logs
castle job      …same verbs; create takes --schedule
castle tool     list|info|install|uninstall                    # CLIs on your PATH

# Platform-wide
castle list [--kind K] [--stack S] [--json]   # catalog + every deployment view
castle status                                 # unified runtime status
castle doctor                                 # diagnose setup + health, with fix hints
castle deploy [name]                          # apply config → units + Caddyfile
castle start | stop | restart                 # all deployments (+ gateway)
castle gateway start|stop|reload|status
```

`castle tool list --json` is the machine-readable tool catalog assistants use to
build context — it surfaces each tool's actual **executable** (which can differ from
the program name, e.g. `litellm-intent-router` installs `intent-router`), its
description, and whether it's installed.

## Configuration

The registry lives under `~/.castle/`: a global `castle.yaml` plus one file per
resource under `programs/` and `deployments/`.

```yaml
# ~/.castle/castle.yaml — globals
gateway:
  port: 9000
repo: /data/repos/castle     # resolves `source: repo:<name>` for castle's own programs
```

```yaml
# ~/.castle/programs/my-api.yaml — the catalog entry
description: Does something useful
source: /data/repos/my-api
stack: python-fastapi
```

```yaml
# ~/.castle/deployments/my-api.yaml — a systemd service (derived kind: service)
program: my-api
manager: systemd
run: { launcher: python, program: my-api }
expose: { http: { internal: { port: 9001 }, health_path: /health } }
proxy: true                        # served at my-api.<gateway.domain>
manage: { systemd: {} }
defaults:
  env:
    MY_API_PORT: ${port}           # = expose.http.internal.port
    MY_API_DATA_DIR: ${data_dir}   # = $CASTLE_DATA_DIR/my-api
    API_KEY: ${secret:MY_API_KEY}
```

`defaults.env` is the **single, explicit source** of a deployment's environment —
Castle injects nothing implicitly. The placeholders `${port}`, `${data_dir}`,
`${name}`, `${public_url}`, and `${secret:NAME}` map your program's own env var names
to Castle's computed values. Secrets live in `~/.castle/secrets/` (never in a repo).

## Gateway, DNS & TLS

Every gateway-exposed deployment gets its own subdomain — `<name>.<gateway.domain>`
— routed to it by the Caddy gateway (there are no path-prefix routes). Exposure is a
single checkbox: `proxy: true` on a service, while a static deployment is inherently
served. The dashboard is `castle.<domain>` and the API `castle-api.<domain>`; on a
node with no domain, `:9000` serves the dashboard plus a `/api` proxy.

`gateway.tls` is a per-node choice: `off` (plain HTTP on `:9000`) or `acme` (a real
Let's Encrypt wildcard `*.<domain>` via a DNS-01 challenge — publicly trusted, no CA
to install, while the services stay internal-only). Reaching a service from the
public internet is separately opt-in via a Cloudflare tunnel (`public: true`). See
[docs/dns-and-tls.md](docs/dns-and-tls.md).

## Layout

```
~/.castle/                 # instance: config, artifacts, secrets
  castle.yaml              #   globals (gateway, repo, agents)
  programs/  deployments/  #   one file per program / deployment
  secrets/                 #   secret files (mode 700)
  artifacts/specs/         #   generated Caddyfile, registry.yaml
/data/repos/<name>/        # your program source (absolute source:)
/data/castle/<name>/       # per-deployment data volume
<repo>/                    # castle itself: cli/ core/ castle-api/ app/ docs/
```

**Independence principle:** your programs never depend on Castle. They accept
configuration (data dir, port, URLs) via environment variables; only Castle's own
programs (CLI, API, gateway) know Castle internals.

## Dashboard & API

The **dashboard** (`app/`, served at `castle.<domain>` or `http://localhost:9000`)
lists programs and deployments, edits their config, drives lifecycle, shows the
gateway route table and logs, and hosts the agent terminal dock.

**`castle-api`** (port 9020, proxied at `castle-api.<domain>`) is the control plane:
`/deployments`, `/programs`, `/services`, `/jobs`, `/gateway`, `/status`, an SSE
`/stream`, config editing under `/config/…`, and the agent session endpoints under
`/agents`. The full endpoint reference is in [CLAUDE.md](CLAUDE.md).

## Mesh (opt-in)

Castle nodes can discover each other via MQTT + mDNS to form a personal
infrastructure mesh — the gateway can route to services on other nodes and the
dashboard shows discovered nodes and cross-node routes. It's all off by default;
single-node needs none of it. Enable on `castle-api` via `CASTLE_API_MQTT_ENABLED`
and `CASTLE_API_MDNS_ENABLED`.

## Docs

- [docs/registry.md](docs/registry.md) — the registry model, `castle.yaml`, deployment fields, lifecycle
- [docs/dns-and-tls.md](docs/dns-and-tls.md) — gateway routing, DNS, the `off` / `acme` TLS modes
- [docs/stacks/](docs/stacks/) — per-stack guides (python-fastapi, python-cli, react-vite, supabase)
- [AGENTS.md](AGENTS.md) — the canonical, assistant-agnostic operator guide (recipes, gateway, tunnel, mesh)
