# Findings — adopting `lakehouse` as a castle service

A completeness/UX test: take an existing daemon (`/data/repos/lakehouse`, a
FastAPI `lakehoused` server on port 8420 that bundles its own SPA, normally
started by a bespoke `lakehouse start`) and bring it fully under castle —
systemd-managed, health-checked, proxied, on the dashboard.

## What worked cleanly

- `castle add` auto-detected `behavior: daemon` + `stack: python-fastapi` from
  the pyproject (fastapi/uvicorn in deps).
- Adding the service via the config API (`PUT /config/services/lakehouse`)
  validated and persisted correctly.
- `castle deploy lakehouse` produced a correct systemd unit, registry entry,
  and Caddy route, and auto-installed the editable package.
- `castle service enable lakehouse` started it and enabled it on boot.
- Health probe (direct `127.0.0.1:8420`) and dashboard data
  (program / service / deployment / `active`) were all correct.

## Gaps found

### #1 — No CLI/app path to create a service from an adopted daemon (High)

`castle add` writes a `daemon`-behavior **program**, but there is no command to
turn it into a running **service** (port, health, proxy, systemd). We had to
hand the service block to the config API. Worse: `castle install <daemon>` on a
program with no service silently falls through to the *tool* install path
(`uv tool install`) instead of running it — a dead end.

**Fix:** `castle expose <program> [--port --health --path]` to scaffold a
service entry from an existing program. (App needs an equivalent "add service"
flow — tracked separately.)

### #2 — castle can't actually configure an adopted program's port / data dir (Medium)

The generated unit injects castle's convention vars `LAKEHOUSE_PORT=8420` and
`LAKEHOUSE_DATA_DIR=…`, but `lakehoused` reads **`LAKEHOUSED_DAEMON_PORT`** and
its own storage paths — it ignores both. The port "worked" only because 8420 is
the daemon's built-in default and we declared the same value. Castle's
convention assumes a castle-aware program; an adopted one doesn't read
`<PREFIX>_PORT`.

**Fix:** let a service declare which env var carries the port, e.g.
`expose.http.port_env: LAKEHOUSED_DAEMON_PORT`, so castle sets *that* to the
configured port and genuinely drives the bind. (`defaults.env` is the manual
workaround.)

### #3 — `castle deploy` regenerates the Caddyfile but never reloads Caddy (High, bug)

Deploy wrote the new `/lakehouse` route to the Caddyfile on disk but didn't
reload the running gateway, so every `/lakehouse/*` request fell through to the
castle-app catch-all and returned the dashboard's `index.html` (a misleading
`200`). `castle service enable` doesn't reload either, and the deploy output
never mentions `castle gateway reload`.

**Fix:** `castle deploy` (and `service enable`) reload the gateway when proxy
routes changed.

### #4 — Path-prefix proxying breaks root-based SPAs (Medium, architectural)

`lakehoused`'s bundled webapp is built with Vite `base: "/"` — its `index.html`
references assets at absolute `/assets/…`. Proxied at `/lakehouse/`, the browser
requests `/assets/…` (no prefix), which hits the castle-app catch-all → the UI
can't boot. The API works through the gateway; the UI only works directly at
`:8420/`.

Two distinct cases, because Vite bakes `base` in at **build** time (a runtime
env in the unit is too late to rebase a pre-built bundle):

- **Case A — frontends castle builds** (the `react-vite` stack, served by
  `file_server`). Castle runs `pnpm build` *and* knows the serve prefix, so it
  can pass `--base=/<prefix>/` automatically. Today `power-graph-app` only works
  because its base was hand-set to match.
  **Fix:** derive the build `--base` from the serve path prefix.
- **Case B — adopted daemons that self-serve a root SPA** (lakehouse). Castle
  never runs their build, so it can't pass `--base`. The clean answer is
  **host-based routing** (`lakehouse.civil.lan → :8420`) so `base: "/"` stays
  valid — also a generally useful castle capability.
  **Fix:** support proxy-by-hostname in the Caddyfile generator + manifest.

### Nits

- **Redundant editable reinstall:** `castle deploy` installs the package, then
  `castle install`/activate may `uv tool install` it again.
- **Entry-point discovery:** the service's `run.program` had to be `lakehoused`,
  not `lakehouse` — the package ships two console scripts and castle gives no
  hint which is the server. Surfacing a package's `[project.scripts]` would help.
