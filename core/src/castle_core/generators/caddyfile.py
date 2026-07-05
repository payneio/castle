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

import os
from dataclasses import dataclass
from pathlib import Path

from castle_core.config import SPECS_DIR, CastleConfig
from castle_core.manifest import CaddyDeployment, SystemdDeployment
from castle_core.registry import NodeRegistry

# DNS-01 provider → the env var the Caddyfile reads its API token from. The token
# reaches Caddy via the gateway service's defaults.env (a mode-0600 EnvironmentFile).
_DNS_TOKEN_ENV = {"cloudflare": "CLOUDFLARE_API_TOKEN"}

# Let's Encrypt staging directory — opt in via CASTLE_ACME_STAGING=1 to avoid the
# production rate limits while testing, then cut over to prod (unset the env var).
_ACME_STAGING_CA = "https://acme-staging-v02.api.letsencrypt.org/directory"


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


# (expose?, port, base_url) — expose=True → route <service-name>.<domain> here.
ProxyTargets = tuple[bool, int | None, str | None]


def service_proxy_targets(name: str, dep: SystemdDeployment) -> ProxyTargets:
    """Derive a systemd deployment's gateway exposure from its spec.

    The single source of truth shared by the registry build (``deploy``) and
    route computation (``compute_routes``), so they never disagree. A gateway
    route is HTTP-only: ``http_exposed`` requires ``reach != off`` *and* an HTTP
    port, so a raw-TCP service (``expose.tcp``) never yields a route here.
    """
    port = None
    if dep.expose and dep.expose.http:
        port = dep.expose.http.internal.port
    return dep.http_exposed, port, None


def _local_routes(
    config: CastleConfig | None, registry: NodeRegistry
) -> list[tuple[str, str, str]]:
    """Each local deployment's route as ``(name, kind, target)``, name-sorted.

    ``kind`` is ``static`` (a caddy deployment — file-serve a built dir) or
    ``proxy`` (a proxied systemd process). Prefers ``castle.yaml``
    (``config.deployments``) so a regenerated Caddyfile reflects the current spec;
    falls back to the deployed registry snapshot when config isn't available.
    """
    out: list[tuple[str, str, str]] = []
    deployments = getattr(config, "deployments", None)
    if deployments is not None:
        for name, dep in sorted(deployments.items()):
            # A disabled deployment is defined but not running — no route (else it
            # would 502). `castle apply` converges it off.
            if not dep.enabled:
                continue
            if isinstance(dep, CaddyDeployment):
                src = _program_source(config, dep.program)
                if src is not None:
                    out.append((name, "static", str(src / dep.root)))
            elif isinstance(dep, SystemdDeployment):
                expose, port, base_url = service_proxy_targets(name, dep)
                if expose and (port or base_url):
                    out.append((name, "proxy", base_url or f"localhost:{port}"))
        return out
    # No config → route from the deployed registry snapshot.
    for name, d in sorted(registry.deployed.items()):
        if not d.enabled:
            continue
        if d.static_root:
            out.append((name, "static", d.static_root))
        elif d.subdomain and (d.port or d.base_url):
            out.append((name, "proxy", d.base_url or f"localhost:{d.port}"))
    return out


def _program_source(config: CastleConfig | None, program: str | None):
    """Absolute source dir of a referenced program (already resolved), or None."""
    if config is None or not program:
        return None
    prog = getattr(config, "programs", {}).get(program)
    if prog and prog.source:
        return Path(prog.source)
    return None


def compute_routes(
    registry: NodeRegistry,
    config: CastleConfig | None = None,
    remote_registries: dict[str, NodeRegistry] | None = None,
) -> list[GatewayRoute]:
    """Build the ordered list of gateway routes. Every route is a host route whose
    address is the service/frontend **name** (published at ``<name>.<domain>``);
    ``proxy`` routes reverse-proxy a local port, ``static`` routes file-serve a
    frontend's dist. Path routes no longer exist. ``remote_registries`` is accepted
    for signature compatibility but cross-node routing is out of scope here."""
    if config is None:
        try:
            from castle_core.config import load_config

            config = load_config()
        except Exception:
            config = None

    node = registry.node.hostname
    routes: list[GatewayRoute] = []

    # Every route comes from a service. `static`-runner services file-serve their
    # built dir; everything else that's exposed reverse-proxies its port/base_url.
    # (Static frontends are `runner: static` services now — no separate program
    # branch, so routing derives from one place.)
    for name, kind, target in _local_routes(config, registry):
        routes.append(GatewayRoute(name, kind, target, name, node))

    return routes


def _host_matcher_block(label: str, host: str, target: str) -> list[str]:
    """A `@host_X host <host> / handle @host_X { reverse_proxy <target> }` block.

    Shared by the off-mode `:<port>` site and the acme wildcard site so the two
    can't drift. `label` names the matcher (service name, or the address)."""
    matcher = f"@host_{label.replace('-', '_').replace('.', '_')}"
    return [
        f"    {matcher} host {host}",
        f"    handle {matcher} {{",
        f"        reverse_proxy {target}",
        "    }",
        "",
    ]


def _host_static_block(label: str, host: str, serve_dir: str) -> list[str]:
    """A host matcher that file-serves a frontend's dist (with SPA fallback)."""
    matcher = f"@host_{label.replace('-', '_').replace('.', '_')}"
    return [
        f"    {matcher} host {host}",
        f"    handle {matcher} {{",
        f"        root * {serve_dir}",
        "        try_files {path} /index.html",
        "        file_server",
        "    }",
        "",
    ]


# Castle's own control plane: the dashboard frontend and the API it calls. These
# names are the subdomains they're published at in acme mode, and the pair served
# on the :<port> site in off mode (no domain → no subdomains).
_DASHBOARD = "castle"
_API = "castle-api"


def generate_caddyfile_from_registry(
    registry: NodeRegistry,
    remote_registries: dict[str, NodeRegistry] | None = None,
) -> str:
    """Render the routes to a Caddyfile. Every exposed service/frontend is a
    subdomain `<name>.<domain>`; there are no path routes.

    Two modes, set by `gateway.tls`:

    - **acme** — one `*.<domain>` site (a single DNS-01 wildcard cert) with a host
      matcher per route: `reverse_proxy` for services, `file_server` for frontends.
      The `:<port>` site just redirects to the dashboard subdomain (the "browse to
      the box by IP" entry).
    - **off / no domain** — no subdomains available, so the `:<port>` site serves
      castle's control plane only: the dashboard at `/` + `reverse_proxy /api/*` →
      castle-api (the one surviving path, for the dashboard's own backend). Other
      services are reachable at their `host:port` directly.
    """
    routes = compute_routes(registry, None, remote_registries)
    node = registry.node
    gw_port = node.gateway_port
    mode = (node.gateway_tls or "").lower()
    domain = node.gateway_domain
    tls_acme = mode == "acme" and bool(domain)
    lines: list[str] = []

    if tls_acme:
        # Global ACME options: LE account email + DNS-01 provider token (from env).
        provider = node.acme_dns_provider or "cloudflare"
        token_env = _DNS_TOKEN_ENV.get(provider, "CLOUDFLARE_API_TOKEN")
        lines.append("{")
        if node.acme_email:
            lines.append(f"    email {node.acme_email}")
        lines.append(f"    acme_dns {provider} {{env.{token_env}}}")
        if os.environ.get("CASTLE_ACME_STAGING") == "1":
            lines.append(f"    acme_ca {_ACME_STAGING_CA}")
        # On issuance/renewal, refresh certs materialized onto raw-TCP services and
        # reload them (idempotent — a no-op when nothing rotated). Requires the
        # events-exec plugin in the gateway's Caddy build, so it's gated on the
        # durable `gateway.cert_hook` flag, set only once that Caddy is in place;
        # false → the block is omitted and a plugin-less gateway parses fine. See
        # docs/tcp-exposure.md §5.
        if getattr(node, "cert_hook", False):
            lines += [
                "    events {",
                "        on cert_obtained exec castle tls reconcile",
                "    }",
            ]
        lines += ["}", ""]
        # One wildcard site → a single cert covers every subdomain; a new service
        # needs no new cert or challenge.
        if routes:
            lines.append(f"*.{domain} {{")
            for r in routes:
                host = f"{r.address}.{domain}"
                if r.kind == "static":
                    lines += _host_static_block(r.name or r.address, host, r.target)
                else:
                    lines += _host_matcher_block(r.name or r.address, host, r.target)
            lines.append("}")
            lines.append("")
        # Redirect the bare gateway port to the dashboard subdomain.
        lines += [
            f":{gw_port} {{",
            f"    redir https://{_DASHBOARD}.{domain}{{uri}}",
            "}",
        ]
        return "\n".join(lines)

    # off mode: HTTP-only control plane on :<port>.
    if mode == "acme" and not domain:
        lines.append("# gateway.tls=acme but gateway.domain is unset — serving the")
        lines.append("# control plane on the gateway port; services are port-only.")
    lines += ["{", "    auto_https off", "}", "", f":{gw_port} {{"]

    api = next((r for r in routes if r.name == _API and r.kind == "proxy"), None)
    if api is not None:
        lines += [
            "    handle_path /api/* {",
            f"        reverse_proxy {api.target}",
            "    }",
            "",
        ]
    app = next((r for r in routes if r.name == _DASHBOARD and r.kind == "static"), None)
    root = app.target if app is not None else str(SPECS_DIR / "app")
    lines += [
        "    handle {",
        f"        root * {root}",
        "        try_files {path} /index.html",
        "        file_server",
        "    }",
        "}",
    ]
    return "\n".join(lines)
