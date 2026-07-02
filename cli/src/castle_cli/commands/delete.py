"""castle delete — remove a program/deployment from the registry AND tear it down.

Deleting cascades: a program's referencing deployments are taken offline (stop +
disable a service/job, uninstall a tool from PATH, drop a static route) before the
config entries are removed, then the runtime is reconciled (`deploy()` prunes
orphan units, regenerates the Caddyfile, reloads the gateway + tunnel) so nothing
is left running or served. Use --source to also delete the source directory.

Persistent *data* a program's stack created (e.g. a Supabase app's Postgres
schema) is destroyed only with --purge-data — it survives an ordinary delete and
is surfaced as a remnant otherwise. One remnant is still only surfaced, not
auto-removed (pending a DNS-token decision): a public service's Cloudflare CNAME.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from castle_cli.config import load_config, save_config


def run_delete(args: argparse.Namespace) -> int:
    config = load_config()
    name = args.name
    resource = getattr(args, "resource", None)  # "program" | "service" | "job" | ...

    # Resolve which sections this delete touches (scoped to one resource). Any
    # deployment resource name (service/job/tool/static/deployment) targets the
    # single deployments/ collection — the kind is derived, not a separate section.
    _DEPLOY_RESOURCES = (None, "service", "job", "tool", "static", "deployment")
    in_programs = name in config.programs and resource in (None, "program")
    in_deployment = name in config.deployments and resource in _DEPLOY_RESOURCES
    if not (in_programs or in_deployment):
        where = f" {resource}" if resource else ""
        print(f"Error: no{where} '{name}' in castle.yaml")
        return 1

    where = [
        s for s, present in (("program", in_programs), ("deployment", in_deployment)) if present
    ]

    # Cascade: every deployment referencing this program is torn down and removed
    # (a program and its 1:1 service/tool/static are one thing to the user). A
    # deployment-only delete targets just the co-named deployment.
    deployments_to_remove: list[str] = []
    if in_programs:
        deployments_to_remove = [
            d for d, spec in config.deployments.items() if spec.program == name
        ]
    if in_deployment and name not in deployments_to_remove:
        deployments_to_remove.append(name)

    # Capture remnant facts BEFORE mutating config: public CNAMEs, and the program
    # entry itself — its stack may own persistent data (a DB schema) that survives
    # a code delete unless --purge-data drops it via the stack's `teardown`.
    public_hosts = _public_hosts(config, deployments_to_remove)
    from castle_core.stacks import get_handler

    program_spec = config.programs.get(name) if in_programs else None
    stack = program_spec.stack if program_spec else None
    handler = get_handler(stack)
    owns_data = bool(getattr(handler, "owns_data", False)) and program_spec is not None

    # Resolve source dir (from the program entry) for the optional --source removal.
    source_dir: Path | None = None
    if in_programs and config.programs[name].source:
        source_dir = Path(config.programs[name].source)

    purge_data = getattr(args, "purge_data", False)
    print(f"Will remove '{name}' from castle.yaml ({', '.join(where)}).")
    if deployments_to_remove:
        print(f"Will tear down deployment(s): {', '.join(deployments_to_remove)}")
    if args.source and source_dir:
        print(f"Will ALSO delete source directory: {source_dir}")
    if owns_data and purge_data:
        print(f"Will ALSO destroy persistent data (stack: {stack}).")

    # Confirm unless --yes.
    if not args.yes:
        prompt = f"Delete '{name}'? [y/N] "
        try:
            if input(prompt).strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except EOFError:
            print("Aborted (no input). Re-run with --yes to confirm non-interactively.")
            return 1

    # Take each deployment offline in its mode, then drop the config entry. Teardown
    # is best-effort — the config is removed even if the runtime is already gone.
    if deployments_to_remove:
        import asyncio

        from castle_core.lifecycle import deactivate

        for d in deployments_to_remove:
            try:
                res = asyncio.run(deactivate(d, config, config.root))
                if getattr(res, "message", None):
                    print(f"  {res.message}")
            except Exception as e:
                print(f"  warning: teardown of '{d}' failed: {e}")
            del config.deployments[d]

    if in_programs:
        del config.programs[name]
    save_config(config)
    print(f"Removed '{name}' from castle.yaml ({', '.join(where)}).")

    # Converge the runtime: prune orphan units, regenerate the Caddyfile (dropping
    # the static route), reload the gateway + tunnel.
    if deployments_to_remove:
        from castle_core.deploy import deploy

        try:
            deploy()
            print("Reconciled runtime (castle deploy).")
        except Exception as e:
            print(f"warning: reconcile (castle deploy) failed — run 'castle deploy': {e}")

    # Optional: delete the source directory.
    if args.source and source_dir:
        if source_dir.exists():
            shutil.rmtree(source_dir)
            print(f"Deleted source directory: {source_dir}")
        else:
            print(f"Source directory not found (already gone): {source_dir}")

    # Surface the remnants we don't yet auto-remove.
    if public_hosts:
        print("\nNote: public DNS record(s) still exist in Cloudflare (not auto-removed):")
        for h in public_hosts:
            print(f"  - {h}")
        print("  Remove them in the Cloudflare dashboard for the public zone.")
    # Persistent data the stack owns: destroy it on --purge-data, else surface it.
    if owns_data:
        if purge_data:
            import asyncio

            try:
                res = asyncio.run(handler.teardown(name, program_spec, config.root))
                print(f"\n{res.output}")
                if res.status != "ok":
                    print("  warning: data teardown reported an error (see above).")
            except Exception as e:
                print(f"\nwarning: data teardown failed: {e}")
        else:
            print(
                f"\nNote: this program's persistent data (stack: {stack}) was left "
                "intact.\n  Re-run with --purge-data to destroy it."
            )

    return 0


def _public_hosts(config, deployment_names: list[str]) -> list[str]:
    """The Cloudflare CNAMEs (<subdomain>.<public_domain>) of any public deployments
    being removed — surfaced so the operator can clean up DNS."""
    gw = getattr(config, "gateway", None)
    public_domain = getattr(gw, "public_domain", None) if gw else None
    if not public_domain:
        return []
    hosts: list[str] = []
    for d in deployment_names:
        spec = config.deployments.get(d)
        if spec is None or not getattr(spec, "public", False):
            continue
        sub = getattr(spec, "subdomain", None) or d
        hosts.append(f"{sub}.{public_domain}")
    return hosts
