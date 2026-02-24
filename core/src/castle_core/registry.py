"""Node registry — per-machine deployment state."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from castle_core.config import CASTLE_HOME

REGISTRY_PATH = CASTLE_HOME / "registry.yaml"
STATIC_DIR = CASTLE_HOME / "static"


@dataclass
class NodeConfig:
    """Per-node identity and settings."""

    hostname: str = ""
    castle_root: str | None = None  # repo path, for dev commands
    gateway_port: int = 9000

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = socket.gethostname()


@dataclass
class DeployedComponent:
    """A component deployed on this node with resolved runtime config."""

    runner: str
    run_cmd: list[str]
    env: dict[str, str] = field(default_factory=dict)
    description: str | None = None
    behavior: str = "daemon"
    stack: str | None = None
    port: int | None = None
    health_path: str | None = None
    proxy_path: str | None = None
    schedule: str | None = None
    managed: bool = False


@dataclass
class NodeRegistry:
    """What's deployed on this node."""

    node: NodeConfig
    deployed: dict[str, DeployedComponent] = field(default_factory=dict)


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
    )

    deployed: dict[str, DeployedComponent] = {}
    for name, comp_data in data.get("deployed", {}).items():
        # Support both old "category" and new "behavior" keys for migration
        behavior = comp_data.get("behavior")
        if behavior is None:
            category = comp_data.get("category", "service")
            behavior = "daemon" if category == "service" else "tool" if category in ("job", "tool") else "frontend" if category == "frontend" else category
        deployed[name] = DeployedComponent(
            runner=comp_data.get("runner", "command"),
            run_cmd=comp_data.get("run_cmd", []),
            env=comp_data.get("env", {}),
            description=comp_data.get("description"),
            behavior=behavior,
            stack=comp_data.get("stack"),
            port=comp_data.get("port"),
            health_path=comp_data.get("health_path"),
            proxy_path=comp_data.get("proxy_path"),
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

    for name, comp in registry.deployed.items():
        entry: dict = {
            "runner": comp.runner,
            "run_cmd": comp.run_cmd,
        }
        if comp.env:
            entry["env"] = comp.env
        if comp.description:
            entry["description"] = comp.description
        entry["behavior"] = comp.behavior
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.port is not None:
            entry["port"] = comp.port
        if comp.health_path:
            entry["health_path"] = comp.health_path
        if comp.proxy_path:
            entry["proxy_path"] = comp.proxy_path
        if comp.schedule:
            entry["schedule"] = comp.schedule
        if comp.managed:
            entry["managed"] = comp.managed
        data["deployed"][name] = entry

    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
