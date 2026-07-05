"""Castle CLI entry point — resource-first command surface.

Operations live under the resource they act on. `program` is the catalog;
`service`, `job`, and `tool` are deployment lenses (systemd services, scheduled
timers, and PATH-installed CLIs); `gateway` is infrastructure. Platform-wide
lifecycle (`start`/`stop`/`restart`/`status`/`deploy`) and the cross-resource
`list` are top-level. Names can collide across resource types (a program and a
service may share a name), so the resource is always explicit.
"""

from __future__ import annotations

import argparse
import sys

from castle_core.stacks import available_stacks

from castle_cli import __version__

DEV_VERBS = ["build", "test", "lint", "format", "type-check", "check"]


def _add_name(p: argparse.ArgumentParser, help: str = "Name", optional: bool = False) -> None:
    p.add_argument("name", nargs="?" if optional else None, help=help)


def _build_program_group(subparsers: argparse._SubParsersAction) -> None:
    prog = subparsers.add_parser("program", help="Manage programs (the software catalog)")
    prog.set_defaults(resource="program")
    sub = prog.add_subparsers(dest="program_command")

    p = sub.add_parser("list", help="List programs")
    p.add_argument(
        "--kind",
        choices=["service", "job", "tool", "static", "reference"],
        help="Filter by derived kind",
    )
    p.add_argument("--stack", help="Filter by stack")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("info", help="Show program details")
    _add_name(p, "Program name")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    p = sub.add_parser("create", help="Scaffold a new program")
    _add_name(p, "Program name")
    p.add_argument("--stack", choices=available_stacks(), default=None)
    p.add_argument("--description", default="", help="Program description")
    p.add_argument("--port", type=int, help="Port (service deployments only)")

    p = sub.add_parser("add", help="Adopt an existing repo (path or git URL)")
    p.add_argument("target", help="Local path or git URL")
    p.add_argument("--name", help="Program name (default: dir/repo name)")
    p.add_argument("--description", default="", help="Program description")

    p = sub.add_parser("clone", help="Clone source for programs with repo:")
    _add_name(p, "Program to clone (default: all with repo:)", optional=True)

    p = sub.add_parser("delete", help="Remove a program from castle.yaml")
    _add_name(p, "Program name")
    p.add_argument("--source", action="store_true", help="Also delete the source directory")
    p.add_argument(
        "--purge-data",
        action="store_true",
        help="Also destroy the program's persistent data (e.g. a supabase app's DB schema)",
    )
    p.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")

    p = sub.add_parser("run", help="Run a program's declared run command")
    _add_name(p, "Program name")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args passed to the program")

    for verb in DEV_VERBS:
        p = sub.add_parser(verb, help=f"Run {verb}")
        _add_name(p, "Program (default: all)", optional=True)


def _build_tool_group(subparsers: argparse._SubParsersAction) -> None:
    """The `tool` lens — programs installed on PATH (path deployments)."""
    grp = subparsers.add_parser("tool", help="Tools on your PATH (the tools lens)")
    grp.set_defaults(resource="tool")
    sub = grp.add_subparsers(dest="tool_command")

    p = sub.add_parser("list", help="List tools with their executable + description")
    p.add_argument("--json", action="store_true", help="Machine-readable output")

    p = sub.add_parser("info", help="Show a tool's executable, description, install state")
    _add_name(p, "Tool name")
    p.add_argument("--json", action="store_true", help="Machine-readable output")


def _add_service_create(sub: argparse._SubParsersAction, kind: str) -> None:
    p = sub.add_parser("create", help=f"Create a {kind} in castle.yaml")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("--program", help="Program this deployment runs (convenience ref)")
    p.add_argument("--description", default="", help="Description")
    p.add_argument("--run", help="Console script / command to run (default: --program or name)")
    p.add_argument("--launcher", choices=["python", "command"], default="python")
    p.add_argument(
        "--env",
        action="append",
        metavar="KEY=VALUE",
        help="Env var for the program (repeatable). Use ${port}/${data_dir}/${name} placeholders.",
    )
    if kind == "service":
        p.add_argument("--port", type=int, help="HTTP port")
        p.add_argument("--health", default="/health", help="Health path (default: /health)")
        p.add_argument(
            "--no-proxy",
            action="store_true",
            help="Port-only; don't expose at <name>.<gateway.domain>",
        )
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
    p.add_argument("--purge-data", action="store_true", help=argparse.SUPPRESS)

    cap = f"{kind.capitalize()} name"
    # Lifecycle is convergence: `castle apply [name]`. `restart` stays as the one
    # imperative bounce that doesn't change desired state.
    _add_name(sub.add_parser("restart", help=f"Restart the {kind} (imperative bounce)"), cap)

    p = sub.add_parser("logs", help=f"View {kind} logs")
    _add_name(p, f"{kind.capitalize()} name")
    p.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p.add_argument("-n", "--lines", type=int, default=50, help="Lines to show (default: 50)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="castle",
        description=(
            "Castle platform CLI — programs, deployments "
            "(services, jobs, tools), and infrastructure"
        ),
    )
    parser.add_argument("--version", action="version", version=f"castle {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    _build_program_group(subparsers)
    _build_deployment_group(subparsers, "service")
    _build_deployment_group(subparsers, "job")
    _build_tool_group(subparsers)

    # Gateway (inspection). The gateway is a deployment — start/stop/reload it via
    # `castle apply` / `castle restart castle-gateway`; this lens just shows routes.
    gw = subparsers.add_parser("gateway", help="Show the gateway's status + route table")
    gw_sub = gw.add_subparsers(dest="gateway_command")
    gw_sub.add_parser("status", help="Show gateway status + routes (the default)")

    # TLS material for raw-TCP services (cert cut from the gateway wildcard).
    tls = subparsers.add_parser(
        "tls", help="Manage castle-materialized TLS certs for raw-TCP services"
    )
    tls_sub = tls.add_subparsers(dest="tls_command")
    tls_sub.add_parser(
        "reconcile", help="Refresh materialized certs from the wildcard + reload changed"
    )
    tls_sub.add_parser("status", help="Show each TLS service's cert fingerprint + expiry")

    # Convergence — the one lifecycle verb. Renders units/Caddyfile/tunnel, then
    # reconciles the runtime to match config (activate/restart/deactivate).
    p = subparsers.add_parser(
        "apply", help="Converge the running system to match config (render + reconcile)"
    )
    p.add_argument("name", nargs="?", help="Single deployment to converge (default: all)")
    p.add_argument(
        "--plan", action="store_true", help="Show the diff without changing anything"
    )

    # Imperative ops (don't change desired state)
    p = subparsers.add_parser("restart", help="Restart deployment(s) — an imperative bounce")
    p.add_argument("name", nargs="?", help="Deployment to restart (default: all)")
    subparsers.add_parser("status", help="Show status across the platform")
    subparsers.add_parser(
        "doctor", help="Diagnose setup + runtime health, with next-step hints"
    )

    # Relationship model — repos, requires edges, and derived status.
    p = subparsers.add_parser(
        "graph", help="Show how programs/deployments relate (repos, requires, status)"
    )
    p.add_argument("--json", action="store_true", help="Output as JSON")

    # Cross-resource overview
    p = subparsers.add_parser("list", help="List programs, services, jobs, and tools")
    p.add_argument(
        "--kind",
        choices=["service", "job", "tool", "static", "reference"],
        help="Filter by derived kind",
    )
    p.add_argument("--stack", help="Filter by stack")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def _dispatch_program(args: argparse.Namespace) -> int:
    sub = args.program_command
    if not sub:
        verbs = "list|info|create|add|clone|delete|run|" + "|".join(DEV_VERBS)
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
    if sub in DEV_VERBS:
        from castle_cli.commands.dev import run_verb

        return run_verb(args, sub)
    return 1


def _dispatch_tool(args: argparse.Namespace) -> int:
    sub = args.tool_command
    if not sub:
        print("Usage: castle tool {list|info}  (install/uninstall → edit config + castle apply)")
        return 1
    if sub == "list":
        from castle_cli.commands.tool import run_tool_list

        return run_tool_list(args)
    if sub == "info":
        from castle_cli.commands.tool import run_tool_info

        return run_tool_info(args)
    return 1


def _dispatch_deployment(args: argparse.Namespace, kind: str) -> int:
    sub = getattr(args, f"{kind}_command")
    if not sub:
        verbs = "list|info|create|delete|restart|logs  (deploy/enable/... → castle apply)"
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
    if sub == "restart":
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
    if cmd == "tool":
        return _dispatch_tool(args)
    if cmd == "gateway":
        from castle_cli.commands.gateway import run_gateway

        return run_gateway(args)
    if cmd == "tls":
        from castle_cli.commands.tls import run_tls

        return run_tls(args)
    if cmd == "apply":
        from castle_cli.commands.apply import run_apply

        return run_apply(args)
    if cmd == "restart":
        from castle_cli.commands.service import run_restart

        return run_restart(args)
    if cmd == "status":
        from castle_cli.commands.service import run_status

        return run_status(args)
    if cmd == "doctor":
        from castle_cli.commands.doctor import run_doctor

        return run_doctor(args)
    if cmd == "graph":
        from castle_cli.commands.graph import run_graph

        return run_graph(args)
    if cmd == "list":
        from castle_cli.commands.list_cmd import run_list

        return run_list(args)

    parser.print_help()
    return 1


def cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    cli()
