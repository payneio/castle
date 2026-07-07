#!/usr/bin/env bash
# Castle Platform — Bootstrap Install
#
# Idempotent script that sets up the infrastructure "control layer":
#   - Docker, Caddy (system binary)
#   - MQTT broker, Postgres (Docker containers or existing)
#   - Neo4j — optional, off by default (opt in with --with-neo4j or the prompt)
#   - Directory structure, systemd lingering, seed configs
#
# Usage:
#   ./install.sh                # Interactive — prompts for existing services + Neo4j
#   ./install.sh --yes          # Non-interactive — containers for MQTT/Postgres, no Neo4j
#   ./install.sh --with-neo4j   # Also set up the optional Neo4j graph database

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CASTLE_HOME="${HOME}/.castle"
CASTLE_CONF="${CASTLE_HOME}/infra.conf"
# Program data lives on a dedicated volume, decoupled from CASTLE_HOME — must match
# castle_core.config._resolve_data_dir (default /data/castle, override CASTLE_DATA_DIR)
# so the data dirs + container mounts created here line up with what castle apply
# generates for the mqtt/postgres/neo4j deployments.
DATA_DIR="${CASTLE_DATA_DIR:-/data/castle}"
# Program source repos (default /data/repos, override CASTLE_REPOS_DIR).
REPOS_DIR="${CASTLE_REPOS_DIR:-/data/repos}"
CASTLE_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Container defaults
MQTT_IMAGE="eclipse-mosquitto:2"
MQTT_PORT=1883
POSTGRES_IMAGE="postgres:17"
POSTGRES_PORT=5432
NEO4J_IMAGE="neo4j:5-community"
NEO4J_BOLT_PORT=7687
NEO4J_HTTP_PORT=7474

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_bold="\033[1m"
_reset="\033[0m"
_green="\033[32m"
_yellow="\033[33m"
_red="\033[31m"

log_step()  { printf "\n${_bold}[*] %s${_reset}\n" "$1"; }
log_ok()    { printf "    ${_green}OK${_reset}"; [ -n "${1:-}" ] && printf " — %s" "$1"; printf "\n"; }
log_skip()  { printf "    ${_yellow}skipped${_reset} (%s)\n" "$1"; }
log_fail()  { printf "    ${_red}FAILED${_reset}: %s\n" "$1"; exit 1; }
log_info()  { printf "    %s\n" "$1"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

cmd_exists() { command -v "$1" &>/dev/null; }

port_in_use() {
    ss -tlnp 2>/dev/null | grep -q ":${1} " && return 0
    return 1
}

ask_yes_no() {
    local prompt="$1" default="${2:-y}"
    if [ "${AUTO_YES:-}" = "1" ]; then
        [ "$default" = "y" ] && return 0 || return 1
    fi
    local yn
    if [ "$default" = "y" ]; then
        read -r -p "    ${prompt} [Y/n] " yn
        yn="${yn:-y}"
    else
        read -r -p "    ${prompt} [y/N] " yn
        yn="${yn:-n}"
    fi
    [[ "$yn" =~ ^[Yy] ]]
}

conf_get() {
    local key="$1"
    if [ -f "$CASTLE_CONF" ]; then
        grep -m1 "^${key}=" "$CASTLE_CONF" 2>/dev/null | cut -d= -f2 || true
    fi
}

conf_set() {
    local key="$1" val="$2"
    mkdir -p "$(dirname "$CASTLE_CONF")"
    if [ -f "$CASTLE_CONF" ] && grep -q "^${key}=" "$CASTLE_CONF" 2>/dev/null; then
        sed -i "s/^${key}=.*/${key}=${val}/" "$CASTLE_CONF"
    else
        echo "${key}=${val}" >> "$CASTLE_CONF"
    fi
}

# Ensure a Docker container is running. Handles three states:
#   - not exists → create
#   - exists but stopped → start
#   - exists and running → skip
ensure_container() {
    local name="$1"
    shift
    local args=("$@")

    if docker inspect "$name" &>/dev/null; then
        local state
        state=$(docker inspect --format '{{.State.Status}}' "$name" 2>/dev/null)
        if [ "$state" = "running" ]; then
            log_skip "already running"
            return 0
        fi
        docker start "$name" >/dev/null
        log_ok "started existing container"
        return 0
    fi

    docker run -d --restart=unless-stopped --name "$name" "${args[@]}" >/dev/null
    log_ok "created and started"
}

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

check_systemd() {
    log_step "Checking systemd"
    if ! cmd_exists systemctl; then
        log_fail "systemd is required but systemctl was not found"
    fi
    log_ok
}

# ---------------------------------------------------------------------------
# Package installation
# ---------------------------------------------------------------------------

ensure_docker() {
    log_step "Ensuring Docker"
    if cmd_exists docker; then
        log_skip "already installed"
        return
    fi
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker.io >/dev/null
    sudo usermod -aG docker "$USER"
    log_ok
    log_info "NOTE: You may need to log out and back in for Docker group access"
}

ensure_caddy() {
    log_step "Ensuring Caddy"
    if cmd_exists caddy; then
        log_skip "already installed"
        return
    fi
    sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https >/dev/null 2>&1
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq caddy >/dev/null
    # Disable the system-level caddy service — castle manages it via user systemd
    sudo systemctl disable --now caddy 2>/dev/null || true
    log_ok
}

# Pinned Caddy version for the DNS-plugin build (reproducible across nodes).
CADDY_DNS_VERSION="${CADDY_DNS_VERSION:-v2.11.4}"

# Build a Caddy with a DNS-provider plugin, required for gateway.tls=acme
# (Let's Encrypt wildcard via DNS-01). Stock apt Caddy has no DNS modules. The
# result goes to /usr/local/bin/caddy, which precedes /usr/bin on PATH, so the
# gateway (a `command` runner resolving `caddy` via PATH) picks it up on the next
# `castle apply` with no spec change. Idempotent and opt-in (--with-dns-plugin).
ensure_caddy_dns_plugin() {
    local provider="${1:-cloudflare}"
    local module
    case "$provider" in
        cloudflare) module="github.com/caddy-dns/cloudflare" ;;
        *) log_fail "Unknown DNS provider '$provider' — add its caddy-dns module to install.sh" ;;
    esac

    log_step "Ensuring Caddy with $provider DNS plugin (for gateway.tls=acme)"
    if [ -x /usr/local/bin/caddy ] \
       && /usr/local/bin/caddy list-modules 2>/dev/null | grep -q "dns.providers.$provider"; then
        log_skip "already present at /usr/local/bin/caddy"
        return
    fi

    cmd_exists go || log_fail "Go toolchain required to build the DNS-plugin Caddy"

    local gobin; gobin="$(go env GOPATH)/bin"
    if [ ! -x "$gobin/xcaddy" ]; then
        log_info "Installing xcaddy..."
        go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest >/dev/null 2>&1 \
            || log_fail "xcaddy install failed"
    fi

    # events-exec: lets the gateway run `castle tls reconcile` on cert issuance/
    # renewal (the cert_obtained hook), so certs materialized onto raw-TCP services
    # refresh automatically. See docs/tcp-exposure.md §5.
    local events_module="github.com/mholt/caddy-events-exec"
    log_info "Building Caddy $CADDY_DNS_VERSION with $module + events-exec (~1 min)..."
    local tmp; tmp="$(mktemp -d)"
    ( cd "$tmp" && "$gobin/xcaddy" build "$CADDY_DNS_VERSION" --with "$module" --with "$events_module" ) \
        || { rm -rf "$tmp"; log_fail "xcaddy build failed"; }
    sudo install -m 0755 "$tmp/caddy" /usr/local/bin/caddy || { rm -rf "$tmp"; log_fail "install failed"; }
    rm -rf "$tmp"

    /usr/local/bin/caddy list-modules 2>/dev/null | grep -q "dns.providers.$provider" \
        || log_fail "built caddy is missing dns.providers.$provider"
    /usr/local/bin/caddy list-modules 2>/dev/null | grep -q "events.handlers.exec" \
        || log_fail "built caddy is missing events.handlers.exec"
    log_info "Built /usr/local/bin/caddy — run 'castle apply' to use it."
    log_ok
}

# ---------------------------------------------------------------------------
# Castle CLI
# ---------------------------------------------------------------------------

ensure_uv() {
    log_step "Ensuring uv (Python package manager)"
    if cmd_exists uv; then
        log_skip "already installed"
        return
    fi
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || log_fail "uv install failed"
    # The installer drops uv in ~/.local/bin — make it visible for the rest of this run.
    export PATH="${HOME}/.local/bin:${PATH}"
    cmd_exists uv || log_fail "uv installed but not on PATH (expected ~/.local/bin)"
    log_ok
}

# Install the `castle` CLI from this repo as an editable uv tool, so a fresh
# clone becomes a working `castle` command. Idempotent — reinstall is cheap and
# keeps the entry point pointed at the current checkout.
install_cli() {
    log_step "Installing the castle CLI"
    ( cd "$CASTLE_ROOT" && uv tool install --editable ./cli >/dev/null 2>&1 ) \
        || log_fail "uv tool install of ./cli failed"
    cmd_exists castle || log_info "NOTE: ensure ~/.local/bin is on your PATH to use 'castle'"
    log_ok
}

# Non-interactive/non-login shells (`ssh host cmd`, systemd units, `castle` dev verbs)
# load ~/.zshenv but NOT ~/.zshrc → ~/.zsh.d/*.sh — so tools installed there (uv,
# castle, pnpm, nvm node) don't resolve over a bare `ssh host 'castle …'`. Mirror just
# the PATH entries into ~/.zshenv (interactive niceties stay in ~/.zsh.d). Idempotent.
ensure_shell_path() {
    log_step "Wiring PATH for non-interactive shells"
    case "${SHELL:-}" in
        */zsh) : ;;
        *)
            if [ ! -e "${HOME}/.zshrc" ] && [ ! -e "${HOME}/.zshenv" ]; then
                log_skip "not a zsh user"
                return
            fi
            ;;
    esac
    local zshenv="${HOME}/.zshenv"
    if [ -f "$zshenv" ] && grep -q "castle non-interactive PATH" "$zshenv"; then
        log_skip "already wired"
        return
    fi
    cat >> "$zshenv" <<'ZSHENV'

# >>> castle non-interactive PATH >>>
# Non-interactive/non-login shells (ssh 'cmd', systemd, castle dev verbs) load
# ~/.zshenv but not ~/.zshrc → ~/.zsh.d/*.sh. Mirror the PATH entries castle's
# toolchain needs (uv/castle in ~/.local/bin, pnpm, nvm node) so they resolve there.
for _d in "$HOME/.local/bin" "$HOME/.local/share/pnpm"; do
  case ":$PATH:" in *":$_d:"*) ;; *) [ -d "$_d" ] && PATH="$_d:$PATH" ;; esac
done
for _nb in "$HOME"/.nvm/versions/node/*/bin(N); do
  case ":$PATH:" in *":$_nb:"*) ;; *) PATH="$_nb:$PATH" ;; esac
done
export PATH
unset _d _nb
# <<< castle non-interactive PATH <<<
ZSHENV
    log_ok "~/.zshenv"
}

# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

create_directories() {
    log_step "Creating directory structure"

    # ~/.castle tree — globals (castle.yaml) plus one file per program/deployment.
    mkdir -p "${CASTLE_HOME}/programs"
    mkdir -p "${CASTLE_HOME}/deployments"
    mkdir -p "${CASTLE_HOME}/artifacts/specs"
    mkdir -p "${CASTLE_HOME}/artifacts/content"
    mkdir -p "${CASTLE_HOME}/secrets" && chmod 700 "${CASTLE_HOME}/secrets"

    # Program data volume (default /data/castle) lives outside $HOME, so on a fresh
    # machine its parent may not be user-writable — fall back to sudo + chown so the
    # later container mounts (and castle apply) can write there.
    if ! mkdir -p "${DATA_DIR}" 2>/dev/null; then
        log_info "creating ${DATA_DIR} (needs sudo — outside \$HOME)"
        sudo mkdir -p "${DATA_DIR}"
        sudo chown "$(id -un):$(id -gn)" "${DATA_DIR}"
    fi

    # Seed a minimal global castle.yaml — never clobber an existing one.
    if [[ -f "${CASTLE_HOME}/castle.yaml" ]]; then
        log_ok
    else
        printf 'gateway:\n  port: 9000\n' > "${CASTLE_HOME}/castle.yaml"
        log_ok "seeded ~/.castle/castle.yaml"
    fi

    # Persist the chosen roots into castle.yaml so every later `castle` (CLI, in the
    # shell) and `castle-api` (service) invocation resolves the SAME dirs from the file
    # — not from a per-process env var that only one of them happens to have. Only when
    # non-default, to keep the file minimal; idempotent (grep-guarded), like repo: below.
    if [ "${DATA_DIR}" != "/data/castle" ]; then
        grep -q "^data_dir:" "${CASTLE_HOME}/castle.yaml" 2>/dev/null \
            || printf 'data_dir: %s\n' "${DATA_DIR}" >> "${CASTLE_HOME}/castle.yaml"
    fi
    if [ "${REPOS_DIR}" != "/data/repos" ]; then
        grep -q "^repos_dir:" "${CASTLE_HOME}/castle.yaml" 2>/dev/null \
            || printf 'repos_dir: %s\n' "${REPOS_DIR}" >> "${CASTLE_HOME}/castle.yaml"
    fi
}

# ---------------------------------------------------------------------------
# Control plane (Castle's own gateway + API + dashboard)
# ---------------------------------------------------------------------------

# Register Castle's own control-plane programs/deployments from bootstrap/ so a
# fresh registry is not empty. Without this, `castle apply`
# would bring up nothing. Never clobbers existing entries (idempotent). The
# gateway deployment carries a `__SPECS_DIR__` placeholder (the source repo has
# no machine-specific paths) that we substitute with this machine's specs dir.
seed_control_plane() {
    log_step "Registering Castle's control plane"
    local specs="${CASTLE_HOME}/artifacts/specs"

    # The `repo:` field lets `source: repo:<name>` resolve castle's own programs.
    if ! grep -q "^repo:" "${CASTLE_HOME}/castle.yaml" 2>/dev/null; then
        printf 'repo: %s\n' "$CASTLE_ROOT" >> "${CASTLE_HOME}/castle.yaml"
    fi

    local seeded=0 f dst
    for f in "${CASTLE_ROOT}"/bootstrap/programs/*.yaml; do
        dst="${CASTLE_HOME}/programs/$(basename "$f")"
        [ -f "$dst" ] || { cp "$f" "$dst"; seeded=1; }
    done
    for f in "${CASTLE_ROOT}"/bootstrap/deployments/*.yaml; do
        dst="${CASTLE_HOME}/deployments/$(basename "$f")"
        [ -f "$dst" ] || { sed "s#__SPECS_DIR__#${specs}#g" "$f" > "$dst"; seeded=1; }
    done

    if [ "$seeded" = "1" ]; then
        log_ok "castle-gateway, castle-api, castle (dashboard)"
    else
        log_skip "already registered"
    fi
}

# ---------------------------------------------------------------------------
# Systemd lingering
# ---------------------------------------------------------------------------

enable_lingering() {
    log_step "Enabling systemd user lingering"
    if loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
        log_skip "already enabled"
        return
    fi
    sudo loginctl enable-linger "$USER"
    log_ok
}

# ---------------------------------------------------------------------------
# Seed configs
# ---------------------------------------------------------------------------

seed_caddyfile() {
    log_step "Seeding Caddyfile"
    local caddyfile="${CASTLE_HOME}/artifacts/specs/Caddyfile"
    if [ -f "$caddyfile" ]; then
        log_skip "already exists"
        return
    fi
    cat > "$caddyfile" << 'EOF'
:9000 {
    respond "Castle is starting. Run 'castle apply' to configure." 200
}
EOF
    log_ok
}

seed_mosquitto_config() {
    local conf="${DATA_DIR}/castle-mqtt/config/mosquitto.conf"
    if [ -f "$conf" ]; then
        return
    fi
    mkdir -p "${DATA_DIR}/castle-mqtt/config"
    mkdir -p "${DATA_DIR}/castle-mqtt/data"
    cat > "$conf" << 'EOF'
listener 1883
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
EOF
}

# ---------------------------------------------------------------------------
# Migration — old container names
# ---------------------------------------------------------------------------

migrate_old_containers() {
    # castle-eclipse-mosquitto → castle-mqtt
    if docker inspect castle-eclipse-mosquitto &>/dev/null 2>&1; then
        log_step "Migrating castle-eclipse-mosquitto → castle-mqtt"
        docker stop castle-eclipse-mosquitto 2>/dev/null || true
        docker rm castle-eclipse-mosquitto 2>/dev/null || true
        systemctl --user stop castle-castle-mqtt.service 2>/dev/null || true
        systemctl --user disable castle-castle-mqtt.service 2>/dev/null || true
        log_ok
    fi
}

# ---------------------------------------------------------------------------
# Infrastructure services
# ---------------------------------------------------------------------------

# Generic provisioning for an infrastructure service:
#   - Check infra.conf for previous choice
#   - Detect if port is in use
#   - Ask user or auto-provision
provision_service() {
    local name="$1"         # e.g. MQTT
    local container="$2"    # e.g. castle-mqtt
    local port="$3"         # e.g. 1883
    local display="$4"      # e.g. "MQTT"
    shift 4
    local docker_args=("$@")

    log_step "${display} (port ${port})"

    # Check previous choice
    local prev
    prev=$(conf_get "$name")

    if [ "$prev" = "existing" ]; then
        log_skip "configured to use existing server"
        return
    fi

    if [ "$prev" = "container" ]; then
        # We previously created a container — ensure it's running
        ensure_container "$container" "${docker_args[@]}"
        return
    fi

    # Check if our own container already exists (maybe from a previous manual setup)
    if docker inspect "$container" &>/dev/null; then
        ensure_container "$container" "${docker_args[@]}"
        conf_set "$name" "container"
        return
    fi

    # No previous choice, no existing container — detect and ask
    if port_in_use "$port"; then
        log_info "Detected: port ${port} is already in use (not a castle container)"
        if ask_yes_no "Use existing ${display} server?"; then
            conf_set "$name" "existing"
            log_ok "using existing ${display} on localhost:${port}"
            return
        fi
        log_info "Port ${port} is in use — cannot start container on same port"
        log_fail "Free port ${port} or choose to use the existing server"
    fi

    # Nothing on the port — install via Docker
    log_info "No existing ${display} detected"
    log_info "Installing ${container} via Docker..."
    ensure_container "$container" "${docker_args[@]}"
    conf_set "$name" "container"
}

setup_mqtt() {
    seed_mosquitto_config
    provision_service "MQTT" "castle-mqtt" "$MQTT_PORT" "MQTT" \
        -p "${MQTT_PORT}:1883" \
        -v "${DATA_DIR}/castle-mqtt/config:/mosquitto/config" \
        -v "${DATA_DIR}/castle-mqtt/data:/mosquitto/data" \
        "$MQTT_IMAGE"
}

setup_postgres() {
    # Ensure password exists
    local pass_file="${CASTLE_HOME}/secrets/POSTGRES_PASSWORD"
    if [ ! -f "$pass_file" ]; then
        openssl rand -base64 24 > "$pass_file"
        chmod 600 "$pass_file"
    fi
    local pg_pass
    pg_pass=$(cat "$pass_file")

    mkdir -p "${DATA_DIR}/postgres/data"

    provision_service "POSTGRES" "castle-postgres" "$POSTGRES_PORT" "Postgres" \
        -p "${POSTGRES_PORT}:5432" \
        -e "POSTGRES_USER=castle" \
        -e "POSTGRES_PASSWORD=${pg_pass}" \
        -e "POSTGRES_DB=castle" \
        -v "${DATA_DIR}/postgres/data:/var/lib/postgresql/data" \
        "$POSTGRES_IMAGE"
}

setup_neo4j() {
    mkdir -p "${DATA_DIR}/neo4j/data"
    mkdir -p "${DATA_DIR}/neo4j/logs"

    provision_service "NEO4J" "castle-neo4j" "$NEO4J_BOLT_PORT" "Neo4j" \
        -p "${NEO4J_HTTP_PORT}:7474" \
        -p "${NEO4J_BOLT_PORT}:7687" \
        -e "NEO4J_AUTH=neo4j/changeme" \
        -v "${DATA_DIR}/neo4j/data:/data" \
        -v "${DATA_DIR}/neo4j/logs:/logs" \
        "$NEO4J_IMAGE"
}

# Neo4j is optional — off by default (a graph DB isn't core; don't foist it on new
# users). Enable with `--with-neo4j`, an interactive yes, or a previous run's choice
# (remembered in infra.conf so re-runs don't re-prompt).
maybe_setup_neo4j() {
    local prev; prev=$(conf_get NEO4J)
    if [ "${WITH_NEO4J:-0}" = "1" ] || [ "$prev" = "container" ] || [ "$prev" = "existing" ]; then
        setup_neo4j
        return
    fi
    log_step "Neo4j (optional)"
    if [ "$prev" = "disabled" ]; then
        log_skip "off — enable later with ./install.sh --with-neo4j"
        return
    fi
    if ask_yes_no "Set up Neo4j? (optional graph database — you can add it later)" "n"; then
        setup_neo4j
    else
        conf_set NEO4J "disabled"
        log_skip "off by default — enable later with ./install.sh --with-neo4j"
    fi
}

# ---------------------------------------------------------------------------
# Dashboard build
# ---------------------------------------------------------------------------

# Build the dashboard SPA so the gateway has something to serve at :9000. The
# `castle` program serves `app/dist/` in place; without a build there's no UI.
# Best-effort: a missing pnpm is a warning (the CLI/API still work), not a failure.
build_dashboard() {
    log_step "Building the dashboard"
    if [ ! -d "${CASTLE_ROOT}/app" ]; then
        log_skip "no app/ directory"
        return
    fi
    if ! cmd_exists pnpm; then
        log_skip "pnpm not found — build later with 'castle program build castle'"
        return
    fi
    ( cd "${CASTLE_ROOT}/app" && pnpm install --silent >/dev/null 2>&1 && pnpm build >/dev/null 2>&1 ) \
        || { log_skip "build failed — retry later with 'castle program build castle'"; return; }
    log_ok "app/dist/"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print_summary() {
    printf "\n${_bold}========================================${_reset}\n"
    printf "${_bold}Castle bootstrap complete!${_reset}\n"
    printf "${_bold}========================================${_reset}\n\n"

    printf "Infrastructure:\n"
    printf "  %-20s %s\n" "Caddy" "$(caddy version 2>/dev/null | head -1 || echo 'not found')"
    printf "  %-20s %s\n" "Docker" "$(docker --version 2>/dev/null | head -1 || echo 'not found')"
    printf "\n"

    printf "Services:\n"
    local mqtt_status postgres_status neo4j_status
    mqtt_status=$(conf_get MQTT)
    postgres_status=$(conf_get POSTGRES)
    neo4j_status=$(conf_get NEO4J)
    printf "  %-20s %s (port %s)\n" "MQTT" "${mqtt_status:-not configured}" "$MQTT_PORT"
    printf "  %-20s %s (port %s)\n" "Postgres" "${postgres_status:-not configured}" "$POSTGRES_PORT"
    printf "  %-20s %s (port %s)\n" "Neo4j" "${neo4j_status:-not configured}" "$NEO4J_BOLT_PORT"
    printf "\n"

    printf "Directories:\n"
    printf "  %-20s %s\n" "Castle home" "$CASTLE_HOME"
    printf "  %-20s %s\n" "Repos" "$REPOS_DIR"
    printf "  %-20s %s\n" "Artifacts" "${CASTLE_HOME}/artifacts"
    printf "  %-20s %s\n" "Data" "$DATA_DIR"
    printf "  %-20s %s\n" "Secrets" "${CASTLE_HOME}/secrets"
    printf "\n"

    printf "Next steps:\n"
    printf "  castle apply                  # Converge: render units/routes + start everything\n"
    printf "  castle doctor                 # Verify setup + health (green = good to go)\n"
    printf "  open http://localhost:9000    # the dashboard\n"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    printf "${_bold}========================================${_reset}\n"
    printf "${_bold}Castle Platform — Bootstrap Install${_reset}\n"
    printf "${_bold}========================================${_reset}\n"

    # Parse args
    AUTO_YES=0
    WITH_DNS_PLUGIN=""   # e.g. "cloudflare" → also build a DNS-plugin Caddy for acme TLS
    WITH_NEO4J=0         # Neo4j is optional and off by default; --with-neo4j opts in
    for arg in "$@"; do
        case "$arg" in
            --yes|-y) AUTO_YES=1 ;;
            --with-dns-plugin) WITH_DNS_PLUGIN="cloudflare" ;;
            --with-dns-plugin=*) WITH_DNS_PLUGIN="${arg#*=}" ;;
            --with-neo4j) WITH_NEO4J=1 ;;
            *) printf "Unknown argument: %s\n" "$arg"; exit 1 ;;
        esac
    done
    export AUTO_YES

    check_systemd
    ensure_docker
    ensure_caddy
    [ -n "$WITH_DNS_PLUGIN" ] && ensure_caddy_dns_plugin "$WITH_DNS_PLUGIN"
    ensure_uv
    install_cli
    ensure_shell_path
    create_directories
    seed_control_plane
    enable_lingering
    seed_caddyfile
    migrate_old_containers
    setup_mqtt
    setup_postgres
    maybe_setup_neo4j
    build_dashboard
    print_summary
}

main "$@"
