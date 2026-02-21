"""castle gateway - manage the Caddy reverse proxy gateway."""

from __future__ import annotations

import argparse
import shutil
import subprocess

from castle_cli.config import GENERATED_DIR, CastleConfig, ensure_dirs, load_config


def _find_dashboard_dist(config: CastleConfig) -> str | None:
    """Find the dashboard dist/ directory if it exists."""
    dist = config.root / "dashboard" / "dist"
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

    # Dashboard SPA at root (must come after more-specific handle_path rules)
    dashboard_dist = _find_dashboard_dist(config)
    if dashboard_dist:
        lines.append("    handle {")
        lines.append(f"        root * {dashboard_dist}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
    else:
        # Fallback: serve from generated directory
        fallback = GENERATED_DIR / "dashboard"
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

    dashboard_dist = _find_dashboard_dist(config)
    if dashboard_dist:
        print(f"  Dashboard: {dashboard_dist}")
    else:
        print("  Dashboard: dist/ not found, using fallback")


def run_gateway(args: argparse.Namespace) -> int:
    """Manage the Caddy gateway."""
    if not args.gateway_command:
        print("Usage: castle gateway {start|stop|reload|status}")
        return 1

    config = load_config()

    if args.gateway_command in ("start", "reload") and getattr(args, "dry_run", False):
        return _gateway_dry_run(config)

    if args.gateway_command == "start":
        return _gateway_start(config)
    elif args.gateway_command == "stop":
        return _gateway_stop()
    elif args.gateway_command == "reload":
        return _gateway_reload(config)
    elif args.gateway_command == "status":
        return _gateway_status()

    return 1


def _gateway_dry_run(config: CastleConfig) -> int:
    """Print generated Caddyfile and gateway unit without applying."""
    from castle_cli.commands.service import _generate_gateway_unit

    print("# Caddyfile")
    print(_generate_caddyfile(config))
    print()
    print("# castle-gateway.service")
    print(_generate_gateway_unit(config))
    return 0


def _gateway_start(config: CastleConfig) -> int:
    """Generate config and start Caddy."""
    if not shutil.which("caddy"):
        print("Error: caddy is not installed.")
        print("Install with: sudo apt install caddy")
        return 1

    print("Generating gateway configuration...")
    _write_generated_files(config)

    caddyfile = GENERATED_DIR / "Caddyfile"
    print(f"\nStarting Caddy on port {config.gateway.port}...")

    result = subprocess.run(
        ["caddy", "start", "--config", str(caddyfile), "--adapter", "caddyfile"],
    )

    if result.returncode == 0:
        print(f"Gateway running at http://localhost:{config.gateway.port}")
    else:
        print("Failed to start gateway.")

    return result.returncode


def _gateway_stop() -> int:
    """Stop Caddy."""
    if not shutil.which("caddy"):
        print("Error: caddy is not installed.")
        return 1

    result = subprocess.run(["caddy", "stop"])
    if result.returncode == 0:
        print("Gateway stopped.")
    return result.returncode


def _gateway_reload(config: CastleConfig) -> int:
    """Regenerate config and reload Caddy."""
    print("Regenerating gateway configuration...")
    _write_generated_files(config)

    caddyfile = GENERATED_DIR / "Caddyfile"
    result = subprocess.run(
        ["caddy", "reload", "--config", str(caddyfile), "--adapter", "caddyfile"],
    )

    if result.returncode == 0:
        print("Gateway reloaded.")
    else:
        print("Failed to reload gateway. Is it running?")

    return result.returncode


def _gateway_status() -> int:
    """Show gateway status."""
    if not shutil.which("caddy"):
        print("Gateway: not installed")
        return 1

    result = subprocess.run(
        ["pgrep", "-x", "caddy"],
        capture_output=True,
    )

    if result.returncode == 0:
        print("Gateway: running")
        caddyfile = GENERATED_DIR / "Caddyfile"
        if caddyfile.exists():
            print(f"  Config: {caddyfile}")
    else:
        print("Gateway: stopped")

    return 0
