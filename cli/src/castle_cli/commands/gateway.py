"""castle gateway - manage the Caddy reverse proxy gateway."""

from __future__ import annotations

import argparse
import subprocess

from castle_cli.config import GENERATED_DIR, CastleConfig, ensure_dirs, load_config


GATEWAY_COMPONENT = "castle-gateway"
GATEWAY_UNIT = "castle-castle-gateway.service"


def _find_app_dist(config: CastleConfig) -> str | None:
    """Find the app dist/ directory if it exists."""
    dist = config.root / "app" / "dist"
    if dist.exists() and (dist / "index.html").exists():
        return str(dist)
    return None


def _generate_caddyfile(config: CastleConfig) -> str:
    """Generate Caddyfile content from castle config."""
    lines = [f":{config.gateway.port} {{"]

    # Reverse proxy for each component with proxy.caddy and expose.http
    for name, manifest in config.components.items():
        if not (manifest.proxy and manifest.proxy.caddy and manifest.proxy.caddy.enable):
            continue
        if not (manifest.expose and manifest.expose.http):
            continue

        caddy = manifest.proxy.caddy
        http = manifest.expose.http
        path_prefix = caddy.path_prefix or f"/{name}"
        port = http.internal.port
        host = http.internal.host or "localhost"

        lines.append(f"    handle_path {path_prefix}/* {{")
        lines.append(f"        reverse_proxy {host}:{port}")
        lines.append("    }")
        lines.append("")

    # App SPA at root (must come after more-specific handle_path rules)
    app_dist = _find_app_dist(config)
    if app_dist:
        lines.append("    handle {")
        lines.append(f"        root * {app_dist}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
    else:
        # Fallback: serve from generated directory
        fallback = GENERATED_DIR / "app"
        lines.append("    handle / {")
        lines.append(f"        root * {fallback}")
        lines.append("        file_server")
        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)


def _write_generated_files(config: CastleConfig) -> None:
    """Write generated Caddyfile."""
    ensure_dirs()

    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_path.write_text(_generate_caddyfile(config))
    print(f"  Generated {caddyfile_path}")

    app_dist = _find_app_dist(config)
    if app_dist:
        print(f"  App: {app_dist}")
    else:
        print("  App: dist/ not found, using fallback")


def run_gateway(args: argparse.Namespace) -> int:
    """Manage the Caddy gateway."""
    if not args.gateway_command:
        print("Usage: castle gateway {start|stop|reload|status}")
        return 1

    config = load_config()

    if args.gateway_command == "start":
        if getattr(args, "dry_run", False):
            return _gateway_dry_run(config)
        return _gateway_start(config)
    elif args.gateway_command == "stop":
        return _gateway_stop()
    elif args.gateway_command == "reload":
        if getattr(args, "dry_run", False):
            return _gateway_dry_run(config)
        return _gateway_reload(config)
    elif args.gateway_command == "status":
        return _gateway_status()

    return 1


def _gateway_dry_run(config: CastleConfig) -> int:
    """Print generated Caddyfile without applying."""
    print("# Caddyfile")
    print(_generate_caddyfile(config))
    return 0


def _gateway_start(config: CastleConfig) -> int:
    """Generate config and enable the gateway service."""
    from castle_cli.commands.service import _service_enable

    if GATEWAY_COMPONENT not in config.managed:
        print(f"Error: '{GATEWAY_COMPONENT}' not found in castle.yaml or not managed")
        return 1

    print("Generating gateway configuration...")
    _write_generated_files(config)

    print(f"\nStarting gateway on port {config.gateway.port}...")
    return _service_enable(config, GATEWAY_COMPONENT)


def _gateway_stop() -> int:
    """Stop the gateway service."""
    from castle_cli.commands.service import _service_disable

    return _service_disable(GATEWAY_COMPONENT)


def _gateway_reload(config: CastleConfig) -> int:
    """Regenerate config and reload Caddy."""
    print("Regenerating gateway configuration...")
    _write_generated_files(config)

    result = subprocess.run(
        ["systemctl", "--user", "reload", GATEWAY_UNIT],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print("Gateway reloaded.")
    else:
        # Fall back to restart if reload not supported
        print("Reload signal sent. Verifying...")
        result = subprocess.run(
            ["systemctl", "--user", "is-active", GATEWAY_UNIT],
            capture_output=True, text=True,
        )
        if result.stdout.strip() == "active":
            print("Gateway running.")
        else:
            print("Warning: gateway may not be running. Try: castle gateway start")

    return 0


def _gateway_status() -> int:
    """Show gateway status via systemd."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", GATEWAY_UNIT],
        capture_output=True, text=True,
    )
    status = result.stdout.strip()

    if status == "active":
        print("Gateway: running")
    else:
        print(f"Gateway: {status}")

    return 0
