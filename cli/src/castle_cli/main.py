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
    parser.add_argument("--version", action="version", version=f"castle {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # castle list
    list_parser = subparsers.add_parser("list", help="List all programs, services, and jobs")
    list_parser.add_argument(
        "--behavior",
        choices=["daemon", "tool", "frontend"],
        help="Filter by behavior",
    )
    list_parser.add_argument(
        "--stack",
        help="Filter by stack (e.g. python-cli, python-fastapi, react-vite)",
    )
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # castle create
    create_parser = subparsers.add_parser("create", help="Create a new project")
    create_parser.add_argument("name", help="Project name")
    create_parser.add_argument(
        "--stack",
        choices=["python-cli", "python-fastapi", "react-vite"],
        default=None,
        help="Development stack (scaffold template + default behavior). Omit for a bare program.",
    )
    create_parser.add_argument("--description", default="", help="Project description")
    create_parser.add_argument("--port", type=int, help="Port number (daemons only)")

    # castle add — adopt an existing repo as a program
    add_parser = subparsers.add_parser("add", help="Adopt an existing repo (path or git URL)")
    add_parser.add_argument("target", help="Local path to an existing repo, or a git URL to clone")
    add_parser.add_argument("--name", help="Program name (default: directory/repo name)")
    add_parser.add_argument("--description", default="", help="Program description")

    # castle clone — clone repos for programs that declare repo:
    clone_parser = subparsers.add_parser("clone", help="Clone source for programs with repo:")
    clone_parser.add_argument("name", nargs="?", help="Program to clone (default: all with repo:)")

    # castle expose — turn an existing program into a service
    expose_parser = subparsers.add_parser("expose", help="Run an existing program as a service")
    expose_parser.add_argument("name", help="Program to expose")
    expose_parser.add_argument("--port", type=int, help="HTTP port the program binds")
    expose_parser.add_argument("--health", default="/health", help="Health path (default: /health)")
    expose_parser.add_argument("--path", help="Gateway proxy prefix (default: /<name>)")
    expose_parser.add_argument(
        "--host", help="Route by hostname instead of a path prefix (e.g. lakehouse.civil.lan)"
    )
    expose_parser.add_argument("--run", help="Console script / command to run (default: <name>)")
    expose_parser.add_argument(
        "--port-env", help="Env var the program reads for its port (e.g. LAKEHOUSED_DAEMON_PORT)"
    )
    expose_parser.add_argument(
        "--no-proxy", action="store_true", help="Don't add a gateway route"
    )

    # castle delete — remove a program/service/job from the registry
    delete_parser = subparsers.add_parser("delete", help="Remove a program/service/job")
    delete_parser.add_argument("name", help="Program, service, or job name")
    delete_parser.add_argument(
        "--source", action="store_true", help="Also delete the source directory"
    )
    delete_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    # castle info
    info_parser = subparsers.add_parser("info", help="Show program details")
    info_parser.add_argument("name", help="Program, service, or job name")
    info_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # castle test
    test_parser = subparsers.add_parser("test", help="Run tests")
    test_parser.add_argument("name", nargs="?", help="Program to test (default: all)")

    # castle lint
    lint_parser = subparsers.add_parser("lint", help="Run linter")
    lint_parser.add_argument("name", nargs="?", help="Program to lint (default: all)")

    # castle format
    format_parser = subparsers.add_parser("format", help="Format source code")
    format_parser.add_argument("name", nargs="?", help="Program to format (default: all)")

    # castle build
    build_parser = subparsers.add_parser("build", help="Build programs")
    build_parser.add_argument("name", nargs="?", help="Program to build (default: all)")

    # castle type-check
    tc_parser = subparsers.add_parser("type-check", help="Run type checker")
    tc_parser.add_argument("name", nargs="?", help="Program to type-check (default: all)")

    # castle check (composite: lint + type-check + test)
    check_parser = subparsers.add_parser("check", help="Run lint + type-check + test")
    check_parser.add_argument("name", nargs="?", help="Program to check (default: all)")

    # castle install / uninstall — activate / deactivate a program in its mode
    install_parser = subparsers.add_parser(
        "install", help="Activate a program (tool→PATH, service/job→systemd, frontend→served)"
    )
    install_parser.add_argument("name", nargs="?", help="Program to activate (default: all)")
    uninstall_parser = subparsers.add_parser(
        "uninstall", help="Deactivate a program (reverse of install)"
    )
    uninstall_parser.add_argument("name", nargs="?", help="Program to deactivate")

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
    disable_parser = service_sub.add_parser("disable", help="Stop and disable a service")
    disable_parser.add_argument("name", help="Service name")

    # castle services (plural - manage all services)
    services_parser = subparsers.add_parser("services", help="Manage all services together")
    services_sub = services_parser.add_subparsers(dest="services_command")
    services_sub.add_parser("start", help="Start all services and gateway")
    services_sub.add_parser("stop", help="Stop all services and gateway")
    services_sub.add_parser("status", help="Show status of all services and jobs")

    # castle restart — restart a single deployed service or job
    restart_parser = subparsers.add_parser("restart", help="Restart a service or job")
    restart_parser.add_argument("name", help="Service or job name")

    # castle status — unified status (gateway + services + jobs + programs)
    subparsers.add_parser("status", help="Show overall status across the platform")

    # castle up — bring everything online (deploy + start all services)
    subparsers.add_parser("up", help="Deploy and start all services and the gateway")

    # castle logs
    logs_parser = subparsers.add_parser("logs", help="View service/job logs")
    logs_parser.add_argument("name", help="Service or job name")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    logs_parser.add_argument(
        "-n", "--lines", type=int, default=50, help="Number of lines to show (default: 50)"
    )

    # castle run — run a program (declared run) or deployed service in the foreground
    run_parser = subparsers.add_parser("run", help="Run a program or service in the foreground")
    run_parser.add_argument("name", help="Program or service name")
    run_parser.add_argument(
        "extra", nargs=argparse.REMAINDER, help="Extra arguments passed to the target"
    )

    # castle deploy
    deploy_parser = subparsers.add_parser("deploy", help="Deploy to ~/.castle/ (spec → runtime)")
    deploy_parser.add_argument("name", nargs="?", help="Service or job to deploy (default: all)")

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

    elif args.command == "add":
        from castle_cli.commands.add import run_add

        return run_add(args)

    elif args.command == "clone":
        from castle_cli.commands.clone import run_clone

        return run_clone(args)

    elif args.command == "expose":
        from castle_cli.commands.expose import run_expose

        return run_expose(args)

    elif args.command == "delete":
        from castle_cli.commands.delete import run_delete

        return run_delete(args)

    elif args.command == "test":
        from castle_cli.commands.dev import run_test

        return run_test(args)

    elif args.command == "lint":
        from castle_cli.commands.dev import run_lint

        return run_lint(args)

    elif args.command == "format":
        from castle_cli.commands.dev import run_format

        return run_format(args)

    elif args.command == "build":
        from castle_cli.commands.dev import run_build

        return run_build(args)

    elif args.command == "type-check":
        from castle_cli.commands.dev import run_type_check

        return run_type_check(args)

    elif args.command == "check":
        from castle_cli.commands.dev import run_check

        return run_check(args)

    elif args.command == "install":
        from castle_cli.commands.dev import run_install

        return run_install(args)

    elif args.command == "uninstall":
        from castle_cli.commands.dev import run_uninstall

        return run_uninstall(args)

    elif args.command == "gateway":
        from castle_cli.commands.gateway import run_gateway

        return run_gateway(args)

    elif args.command == "service":
        from castle_cli.commands.service import run_service

        return run_service(args)

    elif args.command == "services":
        from castle_cli.commands.service import run_services

        return run_services(args)

    elif args.command == "restart":
        from castle_cli.commands.service import run_restart

        return run_restart(args)

    elif args.command == "status":
        from castle_cli.commands.service import run_status

        return run_status(args)

    elif args.command == "up":
        from castle_cli.commands.service import run_up

        return run_up(args)

    elif args.command == "logs":
        from castle_cli.commands.logs import run_logs

        return run_logs(args)

    elif args.command == "deploy":
        from castle_cli.commands.deploy import run_deploy

        return run_deploy(args)

    elif args.command == "run":
        from castle_cli.commands.run_cmd import run_run

        return run_run(args)

    else:
        parser.print_help()
        return 1


def cli() -> None:
    """Entry point for the CLI."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
