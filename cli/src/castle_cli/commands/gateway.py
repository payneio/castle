"""castle gateway — inspect the Caddy reverse proxy gateway.

The gateway is itself a deployment (`castle-gateway`): start/stop/reload it the
same way as anything else — `castle apply` (render routes + reload), `castle
restart castle-gateway` (bounce), or `enabled: false` + apply (stop). This command
is the read-only inspection lens: is it up, and what's the route table.
"""

from __future__ import annotations

import argparse
import subprocess

from castle_core.registry import REGISTRY_PATH, load_registry

GATEWAY_UNIT = "castle-castle-gateway.service"


def run_gateway(args: argparse.Namespace) -> int:
    """Show the gateway's status + route table (the only gateway verb)."""
    return _gateway_status()


def _gateway_status() -> int:
    """Show gateway status + the full route table (static, proxy, remote)."""
    result = subprocess.run(
        ["systemctl", "--user", "is-active", GATEWAY_UNIT],
        capture_output=True,
        text=True,
    )
    status = result.stdout.strip()
    print(f"Gateway: {'running' if status == 'active' else status}")

    if not REGISTRY_PATH.exists():
        print("  (no registry — run 'castle apply')")
        return 0

    from castle_core.generators.caddyfile import compute_routes

    routes = compute_routes(load_registry())
    if not routes:
        print("  No routes configured.")
        return 0

    # Each route: address → target, tagged by kind. static = files served in
    # place; proxy/remote = reverse-proxied to a process. (Caddyfile order is
    # precedence-sensitive; this table is alphabetical.)
    print(f"\n  {'ADDRESS':24} {'KIND':7} TARGET")
    for r in sorted(routes, key=lambda r: r.address):
        target = r.target.replace("localhost:", ":") if r.kind != "static" else r.target
        print(f"  {r.address:24} {r.kind:7} {target}")
    return 0
