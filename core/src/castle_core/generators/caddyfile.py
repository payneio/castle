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

from castle_core.config import SPECS_DIR, CastleConfig
from castle_core.manifest import ServiceSpec
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


# (proxy_path, proxy_host, port, base_url) for a service's gateway route(s).
ProxyTargets = tuple[str | None, str | None, int | None, str | None]


def service_proxy_targets(name: str, svc: ServiceSpec) -> ProxyTargets:
    """Derive a service's gateway routing fields from its spec.

    The single source of truth shared by the registry build (``deploy``) and
    route computation (``compute_routes``), so the deployed registry and a
    freshly regenerated Caddyfile can never disagree about ports/paths/hosts.
    """
    port = None
    if svc.expose and svc.expose.http:
        port = svc.expose.http.internal.port

    proxy_path = None
    proxy_host = None
    if svc.proxy and svc.proxy.caddy and svc.proxy.caddy.enable:
        caddy = svc.proxy.caddy
        proxy_host = caddy.host
        if caddy.path_prefix:
            proxy_path = caddy.path_prefix
        elif not caddy.host:
            # No explicit path and no host → default to /<name>.
            proxy_path = f"/{name}"

    base_url = getattr(svc.run, "base_url", None)
    return proxy_path, proxy_host, port, base_url


def _local_proxy_targets(
    config: CastleConfig | None, registry: NodeRegistry
) -> list[tuple[str, ProxyTargets]]:
    """Local services' routing fields, name-sorted for deterministic output.

    Prefers ``castle.yaml`` (``config.services``) as the source of truth so a
    regenerated Caddyfile always reflects the current spec — this is what closes
    the registry-staleness drift. Falls back to the deployed registry snapshot
    only when config isn't available (load failed, or a pure-registry context).
    """
    services = getattr(config, "services", None)
    if services is not None:
        return sorted(
            (name, service_proxy_targets(name, svc)) for name, svc in services.items()
        )
    return sorted(
        (name, (d.proxy_path, d.proxy_host, d.port, d.base_url))
        for name, d in registry.deployed.items()
    )


def compute_routes(
    registry: NodeRegistry,
    config: CastleConfig | None = None,
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

    # Local proxy routes, derived from castle.yaml when available (else the
    # deployed registry) so a regenerated Caddyfile tracks the current spec.
    local = _local_proxy_targets(config, registry)

    # Host-based proxy routes (whole host → backend root).
    for name, (proxy_path, proxy_host, port, base_url) in local:
        if proxy_host and (port or base_url):
            target = base_url or f"localhost:{port}"
            routes.append(GatewayRoute(proxy_host, "proxy", target, name, node))

    # Path-prefix proxy routes.
    for name, (proxy_path, proxy_host, port, base_url) in local:
        if proxy_path and (port or base_url):
            local_paths.add(proxy_path)
            target = base_url or f"localhost:{port}"
            routes.append(GatewayRoute(proxy_path, "proxy", target, name, node))

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
