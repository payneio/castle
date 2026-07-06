"""Node registry — per-machine deployment state."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from castle_core.config import CONTENT_DIR, SPECS_DIR

REGISTRY_PATH = SPECS_DIR / "registry.yaml"
STATIC_DIR = CONTENT_DIR  # backwards-compat alias


@dataclass
class NodeConfig:
    """Per-node identity and settings."""

    hostname: str = ""
    castle_root: str | None = None  # repo path, for dev commands
    gateway_port: int = 9000
    # None/"off" → HTTP-only; "internal" → Caddy local-CA HTTPS; "acme" → Let's
    # Encrypt wildcard (*.gateway_domain) via DNS-01.
    gateway_tls: str | None = None
    gateway_domain: str | None = None  # acme: zone for wildcard cert + host subdomains
    acme_email: str | None = None
    acme_dns_provider: str = "cloudflare"
    # Cloudflare tunnel: public services publish at <subdomain>.<public_domain>.
    public_domain: str | None = None
    tunnel_id: str | None = None
    # Emit the cert_obtained → `castle tls reconcile` hook (needs events-exec plugin).
    cert_hook: bool = False

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = socket.gethostname()


@dataclass
class Deployment:
    """A component deployed on this node with resolved runtime config."""

    # Who supervises/realizes this deployment: systemd | caddy | path | none.
    manager: str
    run_cmd: list[str]
    # The systemd launch mechanism (python|command|container|compose|node), or
    # None for the non-process managers (caddy/path/none).
    launcher: str | None = None
    # Optional teardown command emitted as systemd ``ExecStop=`` (e.g. compose
    # ``down``). Empty for launchers whose stop is just SIGTERM to the ExecStart pid.
    stop_cmd: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # Absolute dirs prepended to the unit's default PATH — a resolved toolchain the
    # default tool PATH omits (e.g. a program's pinned nvm node bin). Ignored when
    # the deployment sets its own PATH in env (an explicit PATH is a full override).
    path_prepend: list[str] = field(default_factory=list)
    # Names (never values) of secret-bearing env vars. Their resolved values live
    # only in the mode-0600 env file, never in env/run_cmd/registry — this is for
    # visibility (which secrets a deployment expects).
    secret_env_keys: list[str] = field(default_factory=list)
    description: str | None = None
    # Derived kind: service | job | tool | static | reference.
    kind: str = "service"
    stack: str | None = None
    port: int | None = None
    health_path: str | None = None
    # Exposed at <subdomain>.<gateway.domain> (the subdomain is the service name),
    # or None when the service is reachable only at its host:port.
    subdomain: str | None = None
    # Also projected to the public internet via the tunnel at
    # <subdomain>.<gateway.public_domain>. Requires subdomain.
    public: bool = False
    # Raw-TCP exposure port (postgres, redis, …). Set → reachable at
    # <name>.<gateway.domain>:<tcp_port> via bind + wildcard DNS (no Caddy route).
    tcp_port: int | None = None
    # For `static` runner services: the absolute dir the gateway file_servers.
    # Set → the route is `static` (file_server) rather than `proxy` (reverse_proxy).
    static_root: str | None = None
    base_url: str | None = None
    schedule: str | None = None
    managed: bool = False
    # Declared desired state (from the deployment's `enabled:`). `castle apply`
    # activates enabled deployments and deactivates disabled ones. Default True.
    enabled: bool = True


@dataclass
class NodeRegistry:
    """What's deployed on this node."""

    node: NodeConfig
    deployed: dict[str, Deployment] = field(default_factory=dict)


def load_registry(path: Path | None = None) -> NodeRegistry:
    """Load the node registry from ~/.castle/registry.yaml."""
    if path is None:
        path = REGISTRY_PATH

    if not path.exists():
        raise FileNotFoundError(
            f"Registry not found: {path}\n"
            "Run 'castle deploy' to generate it from castle.yaml."
        )

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ValueError(f"Empty registry: {path}")

    node_data = data.get("node", {})
    node = NodeConfig(
        hostname=node_data.get("hostname", ""),
        castle_root=node_data.get("castle_root"),
        gateway_port=node_data.get("gateway_port", 9000),
        gateway_tls=node_data.get("gateway_tls"),
        gateway_domain=node_data.get("gateway_domain"),
        acme_email=node_data.get("acme_email"),
        acme_dns_provider=node_data.get("acme_dns_provider", "cloudflare"),
        public_domain=node_data.get("public_domain"),
        tunnel_id=node_data.get("tunnel_id"),
        cert_hook=node_data.get("cert_hook", False),
    )

    deployed: dict[str, Deployment] = {}
    for name, comp_data in data.get("deployed", {}).items():
        # New shape carries manager/launcher/kind; legacy carries runner/behavior.
        manager = comp_data.get("manager")
        launcher = comp_data.get("launcher")
        if manager is None:
            runner = comp_data.get("runner", "command")
            manager = {"static": "caddy", "path": "path", "remote": "none"}.get(
                runner, "systemd"
            )
            if manager == "systemd":
                launcher = runner
        kind = comp_data.get("kind")
        if kind is None:
            behavior = comp_data.get("behavior")
            if comp_data.get("schedule"):
                kind = "job"
            elif manager == "caddy" or behavior == "frontend":
                kind = "static"
            elif manager == "path" or behavior == "tool":
                kind = "tool"
            elif manager == "none":
                kind = "reference"
            else:
                kind = "service"
        deployed[name] = Deployment(
            manager=manager,
            launcher=launcher,
            run_cmd=comp_data.get("run_cmd", []),
            stop_cmd=comp_data.get("stop_cmd", []),
            env=comp_data.get("env", {}),
            path_prepend=comp_data.get("path_prepend", []),
            secret_env_keys=comp_data.get("secret_env_keys", []),
            description=comp_data.get("description"),
            kind=kind,
            stack=comp_data.get("stack"),
            port=comp_data.get("port"),
            health_path=comp_data.get("health_path"),
            subdomain=comp_data.get("subdomain"),
            public=comp_data.get("public", False),
            tcp_port=comp_data.get("tcp_port"),
            static_root=comp_data.get("static_root"),
            base_url=comp_data.get("base_url"),
            schedule=comp_data.get("schedule"),
            managed=comp_data.get("managed", False),
            enabled=comp_data.get("enabled", True),
        )

    return NodeRegistry(node=node, deployed=deployed)


def save_registry(registry: NodeRegistry, path: Path | None = None) -> None:
    """Write the node registry to ~/.castle/registry.yaml."""
    if path is None:
        path = REGISTRY_PATH

    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {
        "node": {
            "hostname": registry.node.hostname,
            "gateway_port": registry.node.gateway_port,
        },
        "deployed": {},
    }

    if registry.node.castle_root:
        data["node"]["castle_root"] = registry.node.castle_root

    if registry.node.gateway_tls:
        data["node"]["gateway_tls"] = registry.node.gateway_tls
    if registry.node.gateway_domain:
        data["node"]["gateway_domain"] = registry.node.gateway_domain
    if registry.node.acme_email:
        data["node"]["acme_email"] = registry.node.acme_email
    if registry.node.acme_dns_provider and registry.node.acme_dns_provider != "cloudflare":
        data["node"]["acme_dns_provider"] = registry.node.acme_dns_provider
    if registry.node.public_domain:
        data["node"]["public_domain"] = registry.node.public_domain
    if registry.node.tunnel_id:
        data["node"]["tunnel_id"] = registry.node.tunnel_id
    if registry.node.cert_hook:
        data["node"]["cert_hook"] = registry.node.cert_hook

    for name, comp in registry.deployed.items():
        entry: dict = {
            "manager": comp.manager,
            "run_cmd": comp.run_cmd,
        }
        if comp.launcher:
            entry["launcher"] = comp.launcher
        if comp.stop_cmd:
            entry["stop_cmd"] = comp.stop_cmd
        if comp.env:
            entry["env"] = comp.env
        if comp.path_prepend:
            entry["path_prepend"] = comp.path_prepend
        if comp.secret_env_keys:
            entry["secret_env_keys"] = comp.secret_env_keys
        if comp.description:
            entry["description"] = comp.description
        entry["kind"] = comp.kind
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.port is not None:
            entry["port"] = comp.port
        if comp.health_path:
            entry["health_path"] = comp.health_path
        if comp.subdomain:
            entry["subdomain"] = comp.subdomain
        if comp.public:
            entry["public"] = comp.public
        if comp.tcp_port is not None:
            entry["tcp_port"] = comp.tcp_port
        if comp.static_root:
            entry["static_root"] = comp.static_root
        if comp.base_url:
            entry["base_url"] = comp.base_url
        if comp.schedule:
            entry["schedule"] = comp.schedule
        if comp.managed:
            entry["managed"] = comp.managed
        # Only emit when disabled — default-True omission keeps existing
        # registries byte-identical and matches the load-side default.
        if not comp.enabled:
            entry["enabled"] = comp.enabled
        data["deployed"][name] = entry

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
