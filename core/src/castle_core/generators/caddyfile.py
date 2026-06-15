"""Gateway routes + Caddyfile generation from the node registry.

A single source of truth: `compute_routes()` produces the structured list of
gateway routes; `generate_caddyfile_from_registry()` renders that list to a
Caddyfile, and the API serves the same list to the dashboard — so the route
table always matches what Caddy actually does.

A route maps a public **address** (a path prefix `/foo`, or a host `foo.lan`) to
a **target**, of one **kind**:
  - ``static`` — a built frontend's `dist/`; Caddy serves files (`file_server`).
  - ``proxy``  — a local service on a port; Caddy reverse-proxies.
  - ``remote`` — a service on another node; Caddy reverse-proxies cross-node.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from castle_core.config import SPECS_DIR
from castle_core.registry import NodeRegistry


@dataclass
class GatewayRoute:
    """One gateway route: address → target."""

    address: str  # "/foo" (path prefix, served at /foo/*) or "foo.lan" (host)
    kind: str  # "static" | "proxy" | "remote"
    target: str  # static: serve dir; proxy: "localhost:PORT"/base_url; remote: "host:PORT"
    name: str | None = None  # backing program/service
    node: str | None = None

    @property
    def is_host(self) -> bool:
        return not self.address.startswith("/")


def compute_routes(
    registry: NodeRegistry,
    config: object | None = None,
    remote_registries: dict[str, NodeRegistry] | None = None,
) -> list[GatewayRoute]:
    """Build the full ordered list of gateway routes (host, proxy, remote, static).

    Order matters for Caddy precedence: host matchers first, then path proxies,
    then cross-node, then static frontends (the root app last)."""
    if config is None:
        try:
            from castle_core.config import load_config

            config = load_config()
        except Exception:
            config = None

    node = registry.node.hostname
    routes: list[GatewayRoute] = []
    local_paths: set[str] = set()

    # Host-based proxy routes (whole host → backend root).
    for name, d in registry.deployed.items():
        if d.proxy_host and (d.port or d.base_url):
            target = d.base_url or f"localhost:{d.port}"
            routes.append(GatewayRoute(d.proxy_host, "proxy", target, name, node))

    # Path-prefix proxy routes.
    for name, d in registry.deployed.items():
        if d.proxy_path and (d.port or d.base_url):
            local_paths.add(d.proxy_path)
            target = d.base_url or f"localhost:{d.port}"
            routes.append(GatewayRoute(d.proxy_path, "proxy", target, name, node))

    # Cross-node routes — local paths take precedence.
    if remote_registries:
        for hostname, remote_reg in remote_registries.items():
            for name, d in remote_reg.deployed.items():
                if d.proxy_path and d.port and d.proxy_path not in local_paths:
                    local_paths.add(d.proxy_path)
                    routes.append(
                        GatewayRoute(d.proxy_path, "remote", f"{hostname}:{d.port}", name, hostname)
                    )

    # Static frontends — a behavior=frontend program with build outputs and no
    # service of its own; served in place from <source>/<dist>. castle-app is the
    # root app (/), others mount at /<name>.
    if config is not None:
        for name, prog in sorted(config.programs.items()):
            if prog.behavior != "frontend" or not prog.source:
                continue
            if not (prog.build and prog.build.outputs):
                continue
            if name in config.services:  # self-serving frontend → already a proxy route
                continue
            serve_dir = str(Path(prog.source) / prog.build.outputs[0])
            address = "/" if name == "castle-app" else f"/{name}"
            if address != "/" and address in local_paths:
                continue
            routes.append(GatewayRoute(address, "static", serve_dir, name, node))

    return routes


def generate_caddyfile_from_registry(
    registry: NodeRegistry,
    remote_registries: dict[str, NodeRegistry] | None = None,
) -> str:
    """Render the route list to a Caddyfile."""
    routes = compute_routes(registry, None, remote_registries)
    gw_port = registry.node.gateway_port

    # HTTP-only internal gateway on a non-standard port → disable auto-HTTPS so a
    # named host doesn't pull the listener into TLS or try to bind :80/:443.
    lines = ["{", "    auto_https off", "}", "", f":{gw_port} {{"]

    # Trailing-slash redirect: `handle_path /foo/*` doesn't match the bare `/foo`,
    # so without this the no-slash form falls through to the root catch-all
    # (serving the wrong app). Redirect /foo → /foo/ for each path-prefix route.
    # (Caddy's bare path matcher is exact, so /foo/bar is unaffected.)
    redirs = [r.address for r in routes if r.address.startswith("/") and r.address != "/"]
    for prefix in redirs:
        lines.append(f"    redir {prefix} {prefix}/")
    if redirs:
        lines.append("")

    root_static: GatewayRoute | None = None
    for r in routes:
        if r.kind == "static" and r.address == "/":
            root_static = r  # the root app is the catch-all, emitted last
            continue
        if r.kind == "static":
            lines += [
                f"    handle_path {r.address}/* {{",
                f"        root * {r.target}",
                "        try_files {path} /index.html",
                "        file_server",
                "    }",
                "",
            ]
        elif r.is_host:  # host-based proxy
            matcher = f"@host_{(r.name or r.address).replace('-', '_').replace('.', '_')}"
            lines += [
                f"    {matcher} host {r.address}",
                f"    handle {matcher} {{",
                f"        reverse_proxy {r.target}",
                "    }",
                "",
            ]
        else:  # path-prefix proxy (local or remote)
            if r.kind == "remote":
                lines.append(f"    # {r.name} on {r.node}")
            lines += [
                f"    handle_path {r.address}/* {{",
                f"        reverse_proxy {r.target}",
                "    }",
                "",
            ]

    if root_static is not None:
        lines += [
            "    handle {",
            f"        root * {root_static.target}",
            "        try_files {path} /index.html",
            "        file_server",
            "    }",
        ]
    else:
        lines += [
            "    handle / {",
            f"        root * {SPECS_DIR / 'app'}",
            "        file_server",
            "    }",
        ]

    lines.append("}")
    return "\n".join(lines)
