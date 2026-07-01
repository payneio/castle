# AGENTS.md — Castle

You are working in the **Castle** repository — Paul's personal software platform,
a monorepo of independent programs (services, tools, libraries, frontends) managed
by the `castle` CLI.

## What Castle does

Castle turns a source repo into something running on this node. The two halves:

- **programs/** — the software catalog: what software exists (`source`, `stack`,
  `build`, `system_dependencies`).
- **deployments/** — how a program is realized here, discriminated on its
  **`manager`**: `systemd` (a service, or a job with a `schedule`), `caddy` (a
  static frontend), `path` (a CLI on your PATH), or `none` (an external
  reference). The human-facing **kind** (service/job/tool/static/reference) is
  *derived* from the manager, never stored.

## Using the `castle` CLI

It's resource-first — operations live under the resource they act on:

```bash
castle program create <name> --stack <python-cli|python-fastapi|react-vite>
castle program add <path|git-url>              # adopt an existing repo
castle service create <name> --program <p> --port <n>
castle service deploy <name> && castle service enable <name>
castle gateway reload                          # update reverse-proxy routes
castle deploy && castle start                  # apply config, then start everything
castle status                                  # unified status
castle list --json                             # all deployments, machine-readable
```

Expose a service on the network by setting `proxy: true` (→
`<name>.<gateway.domain>`); add `public: true` for the Cloudflare tunnel.

## Read this first

- **@CLAUDE.md** — full architecture, the complete `castle` verb list, registry
  model, DNS/TLS, and code-style conventions. This is the authoritative guide.
- `docs/registry.md`, `docs/dns-and-tls.md`, and `docs/stacks/*.md` — deep dives.

**Key principle:** regular programs must never depend on castle. They take
standard config (data dir, port, URLs) via env vars; only castle's own programs
(CLI, gateway, api) know castle internals.

Broader context about this machine and Paul's other projects lives at
`/data/.lakehouse/AGENTS.md`.
