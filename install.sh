#!/usr/bin/env bash
# Castle Platform — Bootstrap Install
#
# Idempotent script that sets up the infrastructure "control layer":
#   - Docker, Caddy (system binary)
#   - MQTT broker, Postgres, Neo4j (Docker containers or existing)
#   - Directory structure, systemd lingering, seed configs
#
# Usage:
#   ./install.sh          # Interactive — prompts for existing services
#   ./install.sh --yes    # Non-interactive — use containers for everything

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CASTLE_HOME="${HOME}/.castle"
CASTLE_CONF="${CASTLE_HOME}/infra.conf"
DATA_DIR="${CASTLE_HOME}/data"
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
CADDY_DNS_VERSION="${CADDY_DNS_VERSION:-v2.10.0}"

# Build a Caddy with a DNS-provider plugin, required for gateway.tls=acme
# (Let's Encrypt wildcard via DNS-01). Stock apt Caddy has no DNS modules. The
# result goes to /usr/local/bin/caddy, which precedes /usr/bin on PATH, so the
# gateway (a `command` runner resolving `caddy` via PATH) picks it up on the next
# `castle deploy` with no spec change. Idempotent and opt-in (--with-dns-plugin).
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

    log_info "Building Caddy $CADDY_DNS_VERSION with $module (~1 min)..."
    local tmp; tmp="$(mktemp -d)"
    ( cd "$tmp" && "$gobin/xcaddy" build "$CADDY_DNS_VERSION" --with "$module" ) \
        || { rm -rf "$tmp"; log_fail "xcaddy build failed"; }
    sudo install -m 0755 "$tmp/caddy" /usr/local/bin/caddy || { rm -rf "$tmp"; log_fail "install failed"; }
    rm -rf "$tmp"

    /usr/local/bin/caddy list-modules 2>/dev/null | grep -q "dns.providers.$provider" \
        || log_fail "built caddy is missing dns.providers.$provider"
    log_info "Built /usr/local/bin/caddy — run 'castle deploy && castle gateway restart' to use it."
    log_ok
}

# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

create_directories() {
    log_step "Creating directory structure"

    # ~/.castle tree
    mkdir -p "${CASTLE_HOME}/code"
    mkdir -p "${CASTLE_HOME}/artifacts/specs"
    mkdir -p "${CASTLE_HOME}/artifacts/content"
    mkdir -p "${DATA_DIR}"
    mkdir -p "${CASTLE_HOME}/secrets" && chmod 700 "${CASTLE_HOME}/secrets"

    log_ok
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
    respond "Castle is starting. Run 'castle deploy' to configure." 200
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
    printf "  %-20s %s\n" "Code" "${CASTLE_HOME}/code"
    printf "  %-20s %s\n" "Artifacts" "${CASTLE_HOME}/artifacts"
    printf "  %-20s %s\n" "Data" "$DATA_DIR"
    printf "  %-20s %s\n" "Secrets" "${CASTLE_HOME}/secrets"
    printf "\n"

    printf "Next steps:\n"
    printf "  cd %s\n" "$CASTLE_ROOT"
    printf "  castle deploy            # Generate registry, systemd units, Caddyfile\n"
    printf "  castle services start    # Start all application services\n"
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
    for arg in "$@"; do
        case "$arg" in
            --yes|-y) AUTO_YES=1 ;;
            --with-dns-plugin) WITH_DNS_PLUGIN="cloudflare" ;;
            --with-dns-plugin=*) WITH_DNS_PLUGIN="${arg#*=}" ;;
            *) printf "Unknown argument: %s\n" "$arg"; exit 1 ;;
        esac
    done
    export AUTO_YES

    check_systemd
    ensure_docker
    ensure_caddy
    [ -n "$WITH_DNS_PLUGIN" ] && ensure_caddy_dns_plugin "$WITH_DNS_PLUGIN"
    create_directories
    enable_lingering
    seed_caddyfile
    migrate_old_containers
    setup_mqtt
    setup_postgres
    setup_neo4j
    print_summary
}

main "$@"
