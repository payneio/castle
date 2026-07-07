"""castle mesh — inspect the NATS mesh and manage shared config.

The mesh lives in the running castle-api (it holds the live peer state), so this
command talks to the local API over HTTP rather than reading files.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def _api_base() -> str:
    port = None
    try:
        from castle_core.config import load_config

        config = load_config()
        dep = next((d for _k, d in config.deployments_named("castle-api")), None)
        internal = getattr(getattr(getattr(dep, "expose", None), "http", None), "internal", None)
        port = getattr(internal, "port", None)
    except Exception:
        pass
    return f"http://localhost:{port or 9020}"


def _get(path: str):
    with urllib.request.urlopen(_api_base() + path, timeout=5) as r:  # noqa: S310
        return json.load(r)


def _put(path: str, body: dict):
    req = urllib.request.Request(  # noqa: S310
        _api_base() + path,
        data=json.dumps(body).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
        return json.load(r)


def run_mesh(args: argparse.Namespace) -> int:
    sub = getattr(args, "mesh_command", None) or "status"
    try:
        if sub == "status":
            return _status()
        if sub == "nodes":
            return _nodes()
        if sub == "config":
            return _config(args)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        print(f"error: HTTP {e.code} — {detail}")
        return 1
    except urllib.error.URLError as e:
        print(f"castle-api not reachable ({e.reason}). Is it running + mesh enabled?")
        return 1
    print(f"unknown mesh command: {sub}")
    return 2


def _status() -> int:
    s = _get("/mesh/status")
    on = "connected" if s.get("connected") else "disconnected"
    print(f"mesh: {'enabled' if s.get('enabled') else 'disabled'} ({on})")
    print(f"  transport: {s.get('nats_url')}")
    print(f"  peers ({s.get('peer_count', 0)}): {', '.join(s.get('peers', [])) or '—'}")
    return 0


def _nodes() -> int:
    nodes = _get("/nodes")
    print(f"{'NODE':<14}{'STATUS':<10}{'DEPLOYED':<10}LOCAL")
    for n in nodes:
        if n.get("online"):
            status = "online"
        else:
            status = "stale" if n.get("is_stale") else "offline"
        local = "yes" if n.get("is_local") else ""
        print(f"{n['hostname']:<14}{status:<10}{n.get('deployed_count', 0):<10}{local}")
    return 0


def _config(args: argparse.Namespace) -> int:
    cmd = getattr(args, "mesh_config_command", None) or "list"
    if cmd == "list":
        data = _get("/mesh/config")
        print(f"shared config (this node role: {data.get('role')}):")
        for k in data.get("keys", []):
            print(f"  {k}")
        if not data.get("keys"):
            print("  (none)")
        return 0
    if cmd == "get":
        print(_get(f"/mesh/config/{args.key}").get("value", ""))
        return 0
    if cmd == "set":
        _put(f"/mesh/config/{args.key}", {"value": args.value})
        print(f"set {args.key}")
        return 0
    print(f"unknown config command: {cmd}")
    return 2
