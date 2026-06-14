"""Castle CLI entry point — resource-first command surface.

Operations live under the resource they act on (`program`, `service`, `job`,
`gateway`); platform-wide lifecycle (`start`/`stop`/`restart`/`status`/`deploy`)
and the cross-resource `list` are top-level. Names can collide across resource
types (a program and a service may share a name), so the resource is always
explicit.
"""

from __future__ import annotations

import argparse
import sys

from castle_cli import __version__

DEV_VERBS = ["build", "test", "lint", "format", "type-check", "check"]


def _add_name(p: argparse.ArgumentParser, help: str = "Name", optional: bool = False) -> None:
    p.add_argument("name", nargs="?" if optional else None, help=help)


def _build_program_group(subparsers: argparse._SubParsersAction) -> None:
    prog = subparsers.add_parser("program", help="Manage programs (the software catalog)")
    prog.set_defaults(resource="program")
    sub = prog.add_subparsers(dest="program_command")

    p = sub.add_parser("list", help="List programs")
    p.add_argument("--behavior", choices=["daemon", "tool", "frontend"], help="Filter by behavior")
    p.add_argument("--stack", help="Filter by stack")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("info", help="Show program details")
    _add_name(p, "Program name")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("create", help="Scaffold a new program")
    _add_name(p, "Program name")
    p.add_argument("--stack", choices=["python-cli", "python-fastapi", "react-vite"], default=None)
    p.add_argument("--description", default="", help="Program description")
    p.add_argument("--port", type=int, help="Port (daemons only)")

    p = sub.add_parser("add", help="Adopt an existing repo (path or git URL)")
    p.add_argument("target", help="Local path or git URL")
    p.add_argument("--name", help="Program name (default: dir/repo name)")
    p.add_argument("--description", default="", help="Program description")

    p = sub.add_parser("clone", help="Clone source for programs with repo:")
    _add_name(p, "Program to clone (default: all with repo:)", optional=True)

    p = sub.add_parser("delete", help="Remove a program from castle.yaml")
    _add_name(p, "Program name")
    p.add_argument("--source", action="store_true", help="Also delete the source directory")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    p = sub.add_parser("run", help="Run a program's declared run command")
    _add_name(p, "Program name")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args passed to the program")

    sub.add_parser("install", help="Activate a program (tool→PATH, frontend→served)").add_argument(
        "name", nargs="?", help="Program (default: all)"
    )
    sub.add_parser("uninstall", help="Deactivate a program").add_argument(
        "name", nargs="?", help="Program"
    )

    for verb in DEV_VERBS:
        p = sub.add_parser(verb, help=f"Run {verb}")
        _add_name(p, "Program (default: all)", optional=True)


def _add_service_create(sub: argparse._SubParsersAction, kind: str) -> None:
    p = sub.add_parser("create", help=f"Create a {kind} in castle.yaml")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("--program", help="Program this deployment runs (convenience ref)")
    p.add_argument("--description", default="", help="Description")
    p.add_argument("--run", help="Console script / command to run (default: --program or name)")
    p.add_argument("--runner", choices=["python", "command"], default="python")
    if kind == "service":
        p.add_argument("--port", type=int, help="HTTP port")
        p.add_argument("--health", default="/health", help="Health path (default: /health)")
        p.add_argument("--path", help="Gateway proxy prefix (default: /<name>)")
        p.add_argument("--host", help="Route by hostname instead of a path prefix")
        p.add_argument("--port-env", help="Env var the program reads for its port")
        p.add_argument("--no-proxy", action="store_true", help="Don't add a gateway route")
    else:
        p.add_argument("--schedule", default="0 2 * * *", help="Cron schedule (default: 0 2 * * *)")


def _build_deployment_group(subparsers: argparse._SubParsersAction, kind: str) -> None:
    """Build the `service` or `job` group (shared verb set)."""
    grp = subparsers.add_parser(kind, help=f"Manage {kind}s")
    grp.set_defaults(resource=kind)
    sub = grp.add_subparsers(dest=f"{kind}_command")

    p = sub.add_parser("list", help=f"List {kind}s")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("info", help=f"Show {kind} details")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    _add_service_create(sub, kind)

    p = sub.add_parser("delete", help=f"Remove a {kind} from castle.yaml")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    p.add_argument("--source", action="store_true", help=argparse.SUPPRESS)

    cap = f"{kind.capitalize()} name"
    _add_name(sub.add_parser("deploy", help=f"Deploy this {kind} (unit + gateway)"), cap)

    p = sub.add_parser("enable", help=f"Enable and start the {kind}")
    _add_name(p, cap)
    if kind == "service":
        p.add_argument("--dry-run", action="store_true", help="Print the unit without installing")
    _add_name(sub.add_parser("disable", help=f"Stop and disable the {kind}"), cap)
    _add_name(sub.add_parser("start", help=f"Start the {kind}"), cap)
    _add_name(sub.add_parser("stop", help=f"Stop the {kind}"), cap)
    _add_name(sub.add_parser("restart", help=f"Restart the {kind}"), cap)

    p = sub.add_parser("logs", help=f"View {kind} logs")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p.add_argument("-n", "--lines", type=int, default=50, help="Lines to show (default: 50)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="castle",
        description="Castle platform CLI — programs, services, jobs, and infrastructure",
    )
    parser.add_argument("--version", action="version", version=f"castle {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    _build_program_group(subparsers)
    _build_deployment_group(subparsers, "service")
    _build_deployment_group(subparsers, "job")

    # Gateway (infrastructure)
    gw = subparsers.add_parser("gateway", help="Manage the Caddy gateway")
    gw_sub = gw.add_subparsers(dest="gateway_command")
    p = gw_sub.add_parser("start", help="Start the gateway")
    p.add_argument("--dry-run", action="store_true")
    gw_sub.add_parser("stop", help="Stop the gateway")
    p = gw_sub.add_parser("reload", help="Reload gateway configuration")
    p.add_argument("--dry-run", action="store_true")
    gw_sub.add_parser("status", help="Show gateway status")

    # Platform-wide lifecycle (top-level)
    subparsers.add_parser("start", help="Start all services and the gateway")
    subparsers.add_parser("stop", help="Stop all services and the gateway")
    subparsers.add_parser("restart", help="Restart all services and jobs")
    subparsers.add_parser("status", help="Show status across the platform")
    p = subparsers.add_parser("deploy", help="Apply config to runtime (units + Caddyfile)")
    p.add_argument("name", nargs="?", help="Service/job to deploy (default: all)")

    # Cross-resource overview
    p = subparsers.add_parser("list", help="List programs, services, and jobs")
    p.add_argument("--behavior", choices=["daemon", "tool", "frontend"], help="Filter by behavior")
    p.add_argument("--stack", help="Filter by stack")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def _dispatch_program(args: argparse.Namespace) -> int:
    sub = args.program_command
    if not sub:
        verbs = "list|info|create|add|clone|delete|run|install|uninstall|" + "|".join(DEV_VERBS)
        print(f"Usage: castle program {{{verbs}}}")
        return 1
    if sub == "list":
        from castle_cli.commands.list_cmd import run_list

        return run_list(args)
    if sub == "info":
        from castle_cli.commands.info import run_info

        return run_info(args)
    if sub == "create":
        from castle_cli.commands.create import run_create

        return run_create(args)
    if sub == "add":
        from castle_cli.commands.add import run_add

        return run_add(args)
    if sub == "clone":
        from castle_cli.commands.clone import run_clone

        return run_clone(args)
    if sub == "delete":
        from castle_cli.commands.delete import run_delete

        return run_delete(args)
    if sub == "run":
        from castle_cli.commands.run_cmd import run_run

        return run_run(args)
    if sub == "install":
        from castle_cli.commands.dev import run_install

        return run_install(args)
    if sub == "uninstall":
        from castle_cli.commands.dev import run_uninstall

        return run_uninstall(args)
    if sub in DEV_VERBS:
        from castle_cli.commands.dev import run_verb

        return run_verb(args, sub)
    return 1


def _dispatch_deployment(args: argparse.Namespace, kind: str) -> int:
    sub = getattr(args, f"{kind}_command")
    if not sub:
        verbs = "list|info|create|delete|deploy|enable|disable|start|stop|restart|logs"
        print(f"Usage: castle {kind} {{{verbs}}}")
        return 1
    if sub == "list":
        from castle_cli.commands.list_cmd import run_list

        return run_list(args)
    if sub == "info":
        from castle_cli.commands.info import run_info

        return run_info(args)
    if sub == "create":
        from castle_cli.commands.deploy_create import run_job_create, run_service_create

        return run_service_create(args) if kind == "service" else run_job_create(args)
    if sub == "delete":
        from castle_cli.commands.delete import run_delete

        return run_delete(args)
    if sub == "deploy":
        from castle_cli.commands.deploy import run_deploy

        return run_deploy(args)
    if sub in ("enable", "disable", "start", "stop", "restart"):
        from castle_cli.commands.service import run_job_cmd, run_service_cmd

        return run_service_cmd(args) if kind == "service" else run_job_cmd(args)
    if sub == "logs":
        from castle_cli.commands.logs import run_logs

        return run_logs(args)
    return 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    cmd = args.command
    if cmd == "program":
        return _dispatch_program(args)
    if cmd in ("service", "job"):
        return _dispatch_deployment(args, cmd)
    if cmd == "gateway":
        from castle_cli.commands.gateway import run_gateway

        return run_gateway(args)
    if cmd in ("start", "stop", "restart"):
        from castle_cli.commands.service import run_platform

        return run_platform(args)
    if cmd == "status":
        from castle_cli.commands.service import run_status

        return run_status(args)
    if cmd == "deploy":
        from castle_cli.commands.deploy import run_deploy

        return run_deploy(args)
    if cmd == "list":
        from castle_cli.commands.list_cmd import run_list

        return run_list(args)

    parser.print_help()
    return 1


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
