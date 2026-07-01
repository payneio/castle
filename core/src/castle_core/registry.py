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

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = socket.gethostname()


@dataclass
class Deployment:
    """A component deployed on this node with resolved runtime config."""

    runner: str
    run_cmd: list[str]
    # Optional teardown command emitted as systemd ``ExecStop=`` (e.g. compose
    # ``down``). Empty for runners whose stop is just SIGTERM to the ExecStart pid.
    stop_cmd: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # Names (never values) of secret-bearing env vars. Their resolved values live
    # only in the mode-0600 env file, never in env/run_cmd/registry — this is for
    # visibility (which secrets a deployment expects).
    secret_env_keys: list[str] = field(default_factory=list)
    description: str | None = None
    behavior: str = "daemon"
    stack: str | None = None
    port: int | None = None
    health_path: str | None = None
    # Exposed at <subdomain>.<gateway.domain> (the subdomain is the service name),
    # or None when the service is reachable only at its host:port.
    subdomain: str | None = None
    base_url: str | None = None
    schedule: str | None = None
    managed: bool = False


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
    )

    deployed: dict[str, Deployment] = {}
    for name, comp_data in data.get("deployed", {}).items():
        # Support both old "category" and new "behavior" keys for migration
        behavior = comp_data.get("behavior")
        if behavior is None:
            category = comp_data.get("category", "service")
            behavior = (
                "daemon"
                if category == "service"
                else "tool"
                if category in ("job", "tool")
                else "frontend"
                if category == "frontend"
                else category
            )
        deployed[name] = Deployment(
            runner=comp_data.get("runner", "command"),
            run_cmd=comp_data.get("run_cmd", []),
            stop_cmd=comp_data.get("stop_cmd", []),
            env=comp_data.get("env", {}),
            secret_env_keys=comp_data.get("secret_env_keys", []),
            description=comp_data.get("description"),
            behavior=behavior,
            stack=comp_data.get("stack"),
            port=comp_data.get("port"),
            health_path=comp_data.get("health_path"),
            subdomain=comp_data.get("subdomain"),
            base_url=comp_data.get("base_url"),
            schedule=comp_data.get("schedule"),
            managed=comp_data.get("managed", False),
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

    for name, comp in registry.deployed.items():
        entry: dict = {
            "runner": comp.runner,
            "run_cmd": comp.run_cmd,
        }
        if comp.stop_cmd:
            entry["stop_cmd"] = comp.stop_cmd
        if comp.env:
            entry["env"] = comp.env
        if comp.secret_env_keys:
            entry["secret_env_keys"] = comp.secret_env_keys
        if comp.description:
            entry["description"] = comp.description
        entry["behavior"] = comp.behavior
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.port is not None:
            entry["port"] = comp.port
        if comp.health_path:
            entry["health_path"] = comp.health_path
        if comp.subdomain:
            entry["subdomain"] = comp.subdomain
        if comp.base_url:
            entry["base_url"] = comp.base_url
        if comp.schedule:
            entry["schedule"] = comp.schedule
        if comp.managed:
            entry["managed"] = comp.managed
        data["deployed"][name] = entry

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
