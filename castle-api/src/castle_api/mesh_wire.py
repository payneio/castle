"""Mesh wire format — (de)serialize a NodeRegistry for cross-node transport.

Transport-agnostic (no MQTT/NATS imports). Only the fields needed for mesh
routing are included; env vars, run_cmd, and castle_root are **excluded** to
avoid leaking secrets — this invariant is load-bearing and must be preserved by
any transport that carries this payload.
"""

from __future__ import annotations

import json

from castle_core.registry import (
    Deployment,
    NodeConfig,
    NodeRegistry,
)


def registry_to_json(registry: NodeRegistry) -> str:
    """Serialize a NodeRegistry to JSON (secret-stripped)."""
    data: dict = {
        "node": {
            "hostname": registry.node.hostname,
            "gateway_port": registry.node.gateway_port,
            # acme domain — lets peers build launch URLs (<subdomain>.<gateway_domain>)
            # for this node's exposed apps. Omitted when the node has no domain.
            "gateway_domain": registry.node.gateway_domain,
        },
        "deployed": {},
    }

    for _kind, name, comp in registry.all():
        entry: dict = {
            "manager": comp.manager,
            "launcher": comp.launcher,
            "kind": comp.kind,
        }
        if comp.stack:
            entry["stack"] = comp.stack
        if comp.description:
            entry["description"] = comp.description
        if comp.port is not None:
            entry["port"] = comp.port
        if comp.health_path:
            entry["health_path"] = comp.health_path
        if comp.subdomain:
            entry["subdomain"] = comp.subdomain
        if comp.schedule:
            entry["schedule"] = comp.schedule
        if comp.managed:
            entry["managed"] = comp.managed
        # Socket surface + external target — so a peer can resolve cross-node
        # consumption endpoints (still no secrets: only ports/URLs).
        if getattr(comp, "tcp_port", None) is not None:
            entry["tcp_port"] = comp.tcp_port
        if getattr(comp, "base_url", None):
            entry["base_url"] = comp.base_url
        # requires — deployment refs (no secrets), so peers can draw cross-node deps.
        if getattr(comp, "requires", None):
            entry["requires"] = comp.requires
        data["deployed"][NodeRegistry.key(comp.kind, name)] = entry

    return json.dumps(data)


def json_to_registry(payload: str) -> NodeRegistry:
    """Deserialize a NodeRegistry from a JSON payload."""
    data = json.loads(payload)
    node_data = data.get("node", {})
    node = NodeConfig(
        hostname=node_data.get("hostname", ""),
        castle_root=node_data.get("castle_root"),
        gateway_port=node_data.get("gateway_port", 9000),
        gateway_domain=node_data.get("gateway_domain"),
    )
    deployed: dict[str, Deployment] = {}
    for key, comp_data in data.get("deployed", {}).items():
        key_kind, name = key.split("/", 1) if "/" in key else (None, key)
        kind = comp_data.get("kind") or key_kind or "service"
        deployed[NodeRegistry.key(kind, name)] = Deployment(
            manager=comp_data.get("manager", "systemd"),
            launcher=comp_data.get("launcher"),
            run_cmd=comp_data.get("run_cmd", []),
            env=comp_data.get("env", {}),
            description=comp_data.get("description"),
            name=name,
            kind=kind,
            stack=comp_data.get("stack"),
            port=comp_data.get("port"),
            health_path=comp_data.get("health_path"),
            subdomain=comp_data.get("subdomain"),
            schedule=comp_data.get("schedule"),
            managed=comp_data.get("managed", False),
            tcp_port=comp_data.get("tcp_port"),
            base_url=comp_data.get("base_url"),
            requires=comp_data.get("requires", []),
        )
    return NodeRegistry(node=node, deployed=deployed)
