# Validation Log

## What was implemented

### Castle CLI (`cli/`)
- `castle --version` — shows version
- `castle list [--type] [--json]` — list all projects, filter by type, JSON output
- `castle create <name> --type service|tool|library` — scaffold project, register in castle.yaml
- `castle test [project]` — run tests across one or all projects
- `castle lint [project]` — run ruff across one or all projects
- `castle sync` — git submodule update + uv sync in all projects
- `castle gateway start|stop|reload|status` — manage Caddy reverse proxy
- `castle service enable|disable <name>` — manage individual systemd units
- `castle service status` — show all service statuses
- `castle services start|stop` — start/stop everything

### Registry (`castle.yaml`)
- All 4 existing projects registered with correct types, ports, data dirs
- `castle create` auto-registers new projects
- Auto port assignment for new services

### Gateway (Caddy)
- Caddyfile generated from castle.yaml into `~/.castle/generated/`
- Dashboard HTML with health checks served at root
- Reverse proxy with `handle_path` (strips prefix) for each service
- Gateway managed as its own systemd unit

### Systemd integration
- User units generated under `~/.config/systemd/user/castle-*.service`
- Resolves `uv` to absolute path for systemd
- Resolves `${data_dir}` in env vars
- Creates data dirs via ExecStartPre

### Project templates
- Service: FastAPI, pydantic-settings, lifespan, health endpoint, test fixtures
- Tool: argparse, stdin/stdout, exit codes
- Library: src/ layout, import test
- All templates include CLAUDE.md and pyproject.toml with ruff isort config

### Configuration files
- `castle.yaml` — project registry
- `ruff.toml` — shared ruff config (100-char lines, E/F/I/W rules)
- `pyrightconfig.json` — shared pyright config
- `CLAUDE.md` — updated with full castle system docs
- `recommendations.md` — updated with all decisions

## What was validated

| Test | Result |
|------|--------|
| `castle --version` | 0.1.0 |
| `castle list` | Shows all 4 projects grouped by type |
| `castle list --json` | Valid JSON output |
| `castle list --type service` | Filters correctly |
| `castle create --type service` | Scaffolds, registers, auto-assigns port |
| `castle create --type tool` | Scaffolds, registers |
| `castle create --type library` | Scaffolds, registers |
| `castle create` duplicate | Fails with error message |
| `castle test <project>` | Passes for scaffolded projects |
| `castle lint <project>` | Passes for scaffolded projects |
| `castle sync` | Updates submodules + uv sync in all projects |
| `castle gateway start` | Starts Caddy, dashboard accessible |
| `castle gateway reload` | Regenerates and reloads |
| `castle gateway status` | Shows running/stopped |
| `castle service enable` | Creates unit, enables, starts |
| `castle service disable` | Stops, removes unit |
| `castle service status` | Shows all service statuses with colors |
| `castle services start` | Starts all services + gateway |
| `castle services stop` | Stops everything |
| Gateway reverse proxy | Routes correctly (path prefix stripped) |
| Gateway dashboard | Serves HTML with health check JS |
| Direct service access | All services respond on their ports |
| CLI unit tests | 32/32 passing |
| CLI lint | All checks passed |
