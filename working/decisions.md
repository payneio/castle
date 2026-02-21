# Implementation Decisions

Decisions made during implementation that weren't pre-decided. Paul will review these.

## 1. CLI entry point name

Used `castle` as the command name (via `[project.scripts] castle = "castle_cli.main:main"`).
Package name is `castle-cli` to avoid conflicts, but the command is just `castle`.

## 2. Caddy `handle_path` instead of `handle`

Used `handle_path` in the Caddyfile instead of `handle`. `handle_path` automatically strips
the path prefix before proxying, so `/central-context/health` proxies to `localhost:9000/health`.
Without this, the upstream service would receive the full `/central-context/health` path and
return 404.

## 3. Service auto-port assignment

`castle create --type service` auto-assigns the next available port starting from 9000,
skipping any ports already used by other services or the gateway. This avoids port collisions
without requiring the user to track assignments manually.

## 4. Systemd unit naming convention

All castle systemd units use the prefix `castle-` (e.g., `castle-central-context.service`,
`castle-gateway.service`). This makes them easy to identify and manage as a group.

## 5. `uv` path resolution in systemd units

Systemd user units don't inherit the user's PATH. The CLI resolves `uv` to its absolute
path (via `shutil.which`) when generating unit files so they work regardless of PATH.

## 6. Dashboard health checks use direct ports

The dashboard HTML checks health by fetching directly from each service's port
(e.g., `localhost:9000/health`) rather than going through the gateway. This avoids
circular dependency if the gateway itself is having issues, and gives accurate per-service
health status.

## 7. `castle sync` runs `uv sync` before `git submodule update`

Actually runs submodule update first, then `uv sync` in each project. This way submodules
are at the right commit before dependencies are installed.

## 8. Template test structure

Scaffolded services include a health endpoint test by default. Tools include a placeholder
test. Libraries include an import test. This ensures `castle test` works immediately after
`castle create` without requiring the developer to write tests first.

## 9. `save_config` YAML formatting

When the CLI saves back to `castle.yaml` (e.g., after `castle create`), the YAML output
uses `yaml.dump` with `default_flow_style=False` and `sort_keys=False` to keep the
format readable and maintain insertion order. The format won't be identical to the original
hand-written YAML (e.g., blank lines are lost) but is functionally equivalent.

## 10. Jinja2 dependency

Added jinja2 as a dependency in the CLI's pyproject.toml for potential future template
expansion, but the current scaffold implementation uses plain f-strings. Could be removed
if it's not used soon.
