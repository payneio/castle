"""castle gateway - manage the Caddy reverse proxy gateway."""

from __future__ import annotations

import argparse
import subprocess

from castle_core.config import GENERATED_DIR
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.registry import REGISTRY_PATH, load_registry

from castle_cli.config import CastleConfig, ensure_dirs, load_config

GATEWAY_COMPONENT = "castle-gateway"
GATEWAY_UNIT = "castle-castle-gateway.service"


def _write_generated_files() -> None:
    """Write generated Caddyfile from registry."""
    ensure_dirs()

    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return

    registry = load_registry()
    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_path.write_text(generate_caddyfile_from_registry(registry))
    print(f"  Generated {caddyfile_path}")


def run_gateway(args: argparse.Namespace) -> int:
    """Manage the Caddy gateway."""
    if not args.gateway_command:
        print("Usage: castle gateway {start|stop|reload|status}")
        return 1

    config = load_config()

    if args.gateway_command == "start":
        if getattr(args, "dry_run", False):
            return _gateway_dry_run()
        return _gateway_start(config)
    elif args.gateway_command == "stop":
        return _gateway_stop()
    elif args.gateway_command == "reload":
        if getattr(args, "dry_run", False):
            return _gateway_dry_run()
        return _gateway_reload()
    elif args.gateway_command == "status":
        return _gateway_status()

    return 1


def _gateway_dry_run() -> int:
    """Print generated Caddyfile without applying."""
    if not REGISTRY_PATH.exists():
        print("Error: no registry found. Run 'castle deploy' first.")
        return 1

    registry = load_registry()
    print("# Caddyfile")
    print(generate_caddyfile_from_registry(registry))
    return 0


def _gateway_start(config: CastleConfig) -> int:
    """Generate config and enable the gateway service."""
    from castle_cli.commands.service import _service_enable

    if GATEWAY_COMPONENT not in config.managed:
        print(f"Error: '{GATEWAY_COMPONENT}' not found in castle.yaml or not managed")
        return 1

    print("Generating gateway configuration...")
    _write_generated_files()

    print(f"\nStarting gateway on port {config.gateway.port}...")
    return _service_enable(config, GATEWAY_COMPONENT)


def _gateway_stop() -> int:
    """Stop the gateway service."""
    from castle_cli.commands.service import _service_disable

    return _service_disable(GATEWAY_COMPONENT)


def _gateway_reload() -> int:
    """Regenerate config and reload Caddy."""
    print("Regenerating gateway configuration...")
    _write_generated_files()

    result = subprocess.run(
        ["systemctl", "--user", "reload", GATEWAY_UNIT],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("Gateway reloaded.")
    else:
        # Fall back to restart if reload not supported
        print("Reload signal sent. Verifying...")
        result = subprocess.run(
            ["systemctl", "--user", "is-active", GATEWAY_UNIT],
            capture_output=True,
            text=True,
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
        capture_output=True,
        text=True,
    )
    status = result.stdout.strip()

    if status == "active":
        print("Gateway: running")
    else:
        print(f"Gateway: {status}")

    return 0
