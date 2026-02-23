"""Command-line interface for devbox-connect."""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from .config import ConfigError, load_config
from .tunnel import TunnelManager, TunnelState

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

# State to color mapping
STATE_COLORS = {
    TunnelState.CONNECTED: GREEN,
    TunnelState.CONNECTING: YELLOW,
    TunnelState.DISCONNECTED: RED,
    TunnelState.ERROR: RED,
}

STATE_SYMBOLS = {
    TunnelState.CONNECTED: "[OK]",
    TunnelState.CONNECTING: "[..]",
    TunnelState.DISCONNECTED: "[--]",
    TunnelState.ERROR: "[!!]",
}


def setup_logging(verbose: bool) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s - %(levelname)s - %(message)s" if verbose else "%(message)s"
    logging.basicConfig(level=level, format=format_str)


def print_banner() -> None:
    """Print application banner."""
    print(f"{BOLD}{CYAN}devbox-connect{RESET} - SSH Tunnel Manager")
    print()


def print_status(manager: TunnelManager) -> None:
    """Print current tunnel status."""
    status = manager.get_status()

    for host_key, tunnels in status.items():
        print(f"{BOLD}{host_key}{RESET}")
        for name, tunnel_status in tunnels.items():
            state = tunnel_status.state
            color = STATE_COLORS[state]
            symbol = STATE_SYMBOLS[state]
            local_port = tunnel_status.config.local_port or tunnel_status.config.remote_port
            remote = f"{tunnel_status.config.remote_host}:{tunnel_status.config.remote_port}"

            line = f"  {color}{symbol}{RESET} {name}: localhost:{local_port} -> {remote}"

            if tunnel_status.connections > 0:
                line += f" ({tunnel_status.connections} active)"

            if tunnel_status.error:
                line += f" {RED}({tunnel_status.error}){RESET}"

            print(line)
        print()


def on_status_change(host: str, tunnel: str, state: TunnelState) -> None:
    """Callback for tunnel status changes."""
    color = STATE_COLORS[state]
    symbol = STATE_SYMBOLS[state]
    logging.info(f"{color}{symbol}{RESET} {host}/{tunnel}: {state.value}")


def run_manager(config_path: Path, verbose: bool) -> int:
    """Run the tunnel manager."""
    setup_logging(verbose)
    print_banner()

    # Load configuration
    try:
        config = load_config(config_path)
    except ConfigError as e:
        logging.error(f"Configuration error: {e}")
        return 1

    if not config.hosts:
        logging.error("No tunnels configured")
        return 1

    # Count tunnels
    total_tunnels = sum(len(h.tunnels) for h in config.hosts)
    logging.info(f"Loaded {total_tunnels} tunnel(s) for {len(config.hosts)} host(s)")
    print()

    # Create and start manager
    manager = TunnelManager(config, on_status_change=on_status_change)

    # Handle shutdown signals
    shutdown_requested = False

    def signal_handler(signum: int, frame: object) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            # Force exit on second signal
            sys.exit(1)
        shutdown_requested = True
        print(f"\n{YELLOW}Shutting down...{RESET}")
        manager.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start tunnels
    manager.start()

    # Wait a moment for connections
    time.sleep(2)

    # Print initial status
    print_status(manager)
    print(f"{CYAN}Press Ctrl+C to stop{RESET}")
    print()

    # Keep running until shutdown
    try:
        while not shutdown_requested:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    manager.stop()
    print(f"{GREEN}Stopped{RESET}")
    return 0


def show_status(config_path: Path) -> int:
    """Show status of configured tunnels (quick check)."""
    setup_logging(verbose=False)

    try:
        config = load_config(config_path)
    except ConfigError as e:
        logging.error(f"Configuration error: {e}")
        return 1

    print_banner()
    print(f"Config: {config_path}")
    print()

    for host in config.hosts:
        print(f"{BOLD}{host.user}@{host.host}:{host.port}{RESET}")
        for tunnel in host.tunnels:
            local_port = tunnel.local_port or tunnel.remote_port
            remote = f"{tunnel.remote_host}:{tunnel.remote_port}"
            print(f"  - {tunnel.name}: localhost:{local_port} -> {remote}")
        print()

    return 0


def validate_config(config_path: Path) -> int:
    """Validate configuration file."""
    setup_logging(verbose=False)

    try:
        config = load_config(config_path)
        total_tunnels = sum(len(h.tunnels) for h in config.hosts)
        print(f"{GREEN}Configuration valid{RESET}")
        print(f"  Hosts: {len(config.hosts)}")
        print(f"  Tunnels: {total_tunnels}")
        return 0
    except ConfigError as e:
        print(f"{RED}Configuration invalid: {e}{RESET}")
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="devbox-connect",
        description="SSH tunnel manager for connecting to devbox ports",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("tunnels.yaml"),
        help="Path to configuration file (default: tunnels.yaml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # start command (default)
    start_parser = subparsers.add_parser("start", help="Start tunnels (default)")
    start_parser.add_argument("-v", "--verbose", action="store_true")

    # status command
    subparsers.add_parser("status", help="Show configured tunnels")

    # validate command
    subparsers.add_parser("validate", help="Validate configuration file")

    args = parser.parse_args()

    # Handle default command
    command = args.command or "start"

    if command == "start":
        verbose = getattr(args, "verbose", False)
        return run_manager(args.config, verbose)
    elif command == "status":
        return show_status(args.config)
    elif command == "validate":
        return validate_config(args.config)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
