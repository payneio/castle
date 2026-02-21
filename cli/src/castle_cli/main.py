"""Castle CLI entry point."""

from __future__ import annotations

import argparse
import sys

from castle_cli import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="castle",
        description="Castle platform CLI - manage projects, services, and infrastructure",
    )
    parser.add_argument(
        "--version", action="version", version=f"castle {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # castle list
    list_parser = subparsers.add_parser("list", help="List all components")
    list_parser.add_argument(
        "--role",
        choices=["service", "tool", "worker", "job", "frontend", "remote", "containerized"],
        help="Filter by role",
    )
    list_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # castle create
    create_parser = subparsers.add_parser("create", help="Create a new project")
    create_parser.add_argument("name", help="Project name")
    create_parser.add_argument(
        "--type",
        choices=["service", "tool", "library"],
        required=True,
        help="Project type",
    )
    create_parser.add_argument(
        "--description", default="", help="Project description"
    )
    create_parser.add_argument(
        "--port", type=int, help="Port number (services only)"
    )

    # castle info
    info_parser = subparsers.add_parser("info", help="Show component details")
    info_parser.add_argument("project", help="Component name")
    info_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )

    # castle test
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument("project", nargs="?", help="Project to test (default: all)")

    # castle lint
    lint_parser = subparsers.add_parser("lint", help="Run linter")
    lint_parser.add_argument("project", nargs="?", help="Project to lint (default: all)")

    # castle sync
    subparsers.add_parser("sync", help="Sync submodules and install dependencies")

    # castle gateway
    gateway_parser = subparsers.add_parser("gateway", help="Manage the Caddy gateway")
    gateway_sub = gateway_parser.add_subparsers(dest="gateway_command")
    gw_start = gateway_sub.add_parser("start", help="Start the gateway")
    gw_start.add_argument(
        "--dry-run", action="store_true", help="Print generated config without applying"
    )
    gateway_sub.add_parser("stop", help="Stop the gateway")
    gw_reload = gateway_sub.add_parser("reload", help="Reload gateway configuration")
    gw_reload.add_argument(
        "--dry-run", action="store_true", help="Print generated config without applying"
    )
    gateway_sub.add_parser("status", help="Show gateway status")

    # castle service (singular - manage individual services)
    service_parser = subparsers.add_parser("service", help="Manage a service")
    service_sub = service_parser.add_subparsers(dest="service_command")
    enable_parser = service_sub.add_parser("enable", help="Enable and start a service")
    enable_parser.add_argument("name", help="Service name")
    enable_parser.add_argument(
        "--dry-run", action="store_true", help="Print generated unit without installing"
    )
    disable_parser = service_sub.add_parser(
        "disable", help="Stop and disable a service"
    )
    disable_parser.add_argument("name", help="Service name")
    service_sub.add_parser("status", help="Show status of all services")

    # castle services (plural - manage all services)
    services_parser = subparsers.add_parser(
        "services", help="Manage all services together"
    )
    services_sub = services_parser.add_subparsers(dest="services_command")
    services_sub.add_parser("start", help="Start all services and gateway")
    services_sub.add_parser("stop", help="Stop all services and gateway")

    # castle logs
    logs_parser = subparsers.add_parser("logs", help="View component logs")
    logs_parser.add_argument("name", help="Component name")
    logs_parser.add_argument(
        "-f", "--follow", action="store_true", help="Follow log output"
    )
    logs_parser.add_argument(
        "-n", "--lines", type=int, default=50, help="Number of lines to show (default: 50)"
    )

    # castle run
    run_parser = subparsers.add_parser("run", help="Run a component in the foreground")
    run_parser.add_argument("name", help="Component name")
    run_parser.add_argument(
        "extra", nargs=argparse.REMAINDER, help="Extra arguments passed to the component"
    )

    # castle tool
    tool_parser = subparsers.add_parser("tool", help="Manage tools")
    tool_sub = tool_parser.add_subparsers(dest="tool_command")
    tool_sub.add_parser("list", help="List all tools by category")
    tool_info_parser = tool_sub.add_parser("info", help="Show tool details")
    tool_info_parser.add_argument("name", help="Tool name")

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Import command handlers lazily to keep startup fast
    if args.command == "list":
        from castle_cli.commands.list_cmd import run_list

        return run_list(args)

    elif args.command == "info":
        from castle_cli.commands.info import run_info

        return run_info(args)

    elif args.command == "create":
        from castle_cli.commands.create import run_create

        return run_create(args)

    elif args.command == "test":
        from castle_cli.commands.dev import run_test

        return run_test(args)

    elif args.command == "lint":
        from castle_cli.commands.dev import run_lint

        return run_lint(args)

    elif args.command == "sync":
        from castle_cli.commands.sync import run_sync

        return run_sync(args)

    elif args.command == "gateway":
        from castle_cli.commands.gateway import run_gateway

        return run_gateway(args)

    elif args.command == "service":
        from castle_cli.commands.service import run_service

        return run_service(args)

    elif args.command == "services":
        from castle_cli.commands.service import run_services

        return run_services(args)

    elif args.command == "logs":
        from castle_cli.commands.logs import run_logs

        return run_logs(args)

    elif args.command == "run":
        from castle_cli.commands.run_cmd import run_run

        return run_run(args)

    elif args.command == "tool":
        from castle_cli.commands.tool import run_tool

        return run_tool(args)

    else:
        parser.print_help()
        return 1


def cli() -> None:
    """Entry point for the CLI."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
