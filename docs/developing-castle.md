# Developing Castle

How to work on **Castle's own code** — the CLI, core library, control-plane API,
and dashboard. For *using* Castle to manage software (create/deploy/expose
programs), see the operator guide in [`AGENTS.md`](../AGENTS.md).

## The Castle monorepo

Castle's own programs live in **this git repo** (`source: repo:<name>`) — distinct
from the programs you manage, which live under `/data/repos/<name>/`:

- `cli/` — the `castle` CLI (installed via `uv tool install --editable cli/`)
- `core/` — `castle_core`: manifest models, config loader, generators
- `castle-api/` — the FastAPI control-plane service (port 9020)
- `app/` — the dashboard frontend (React/Vite; program name `castle`, served at
  `castle.<gateway.domain>`)

The root `pyproject.toml` is the **uv workspace** (core, cli, castle-api).

## Key files

- `core/src/castle_core/manifest.py` — Pydantic models: `ProgramSpec`,
  `DeploymentSpec` (discriminated union on `manager`), `LaunchSpec`, `AgentSpec`, …
- `core/src/castle_core/config.py` — config loader (`castle.yaml` + `programs/` +
  `deployments/` → `CastleConfig`), the two roots, `source:` resolution
- `core/src/castle_core/generators/` — systemd unit/timer + Caddyfile generation
- `cli/src/castle_cli/` — resource-first CLI commands; `templates/scaffold.py`
- `castle-api/src/castle_api/` — routes, health polling, SSE `stream.py`, mesh,
  and the agent terminal UX (`agents.py`, `pty_session.py`, `agent_sessions.py`,
  `agent_registry.py`)
- `ruff.toml` / `pyrightconfig.json` — shared lint/type config

## Commands (all projects use uv)

```bash
uv sync
uv run pytest tests/ -v
uv run ruff check . && uv run ruff format .
uv run pyright <paths>
```

Running `uv sync` from a member subdir trims the shared workspace venv — resync
from the repo root to restore all members. Code style: **ruff** (100-char lines),
**pyright**, **pytest** + **pytest-asyncio**; Python **3.13** for services, **3.11+**
for tools/libraries.

## castle-api endpoints (port 9020)

- Core: `GET /health`, `GET /stream` (SSE: health, service-action, mesh)
- Deployments: `GET /deployments[/{name}]`, `GET /status`
- Catalog + editing: `GET /programs[/{name}]`, `POST /programs/{name}/{action}`,
  `PUT|DELETE /programs/{name}`; likewise `/services`, `/jobs`
- Config: `GET|PUT /`, `POST /apply`, `POST /deploy`
- Gateway: `GET /gateway`, `GET /gateway/caddyfile`, `POST /gateway/reload`
- Mesh: `GET /mesh/status`, `GET /nodes[/{hostname}]`
- Agents (dashboard terminal UX): `GET /agents`, `GET /agents/sessions`,
  `GET /agents/history`, `DELETE /agents/sessions/{id}`, `WS /agents/{name}/session`
- Service actions: `POST /services/{name}/{action}`, `GET /services/{name}/unit`

## Infrastructure internals

- Generated Caddyfile at `~/.castle/artifacts/specs/Caddyfile`; a **plugin Caddy**
  at `/usr/local/bin/caddy` when `tls: acme`.
- Systemd user units at `~/.config/systemd/user/castle-*.service` (+ `.timer`);
  the unit for program `X` is `castle-X.service`. Use drop-in `*.service.d/*.conf`
  for extra env `castle deploy` shouldn't overwrite.
- The `container` launcher resolves docker via `shutil.which("docker")` (preferred
  over rootless podman on this box).
- Service data at `$CASTLE_DATA_DIR/<name>/`; secrets at `~/.castle/secrets/`
  (mode 700) — never in project directories.
