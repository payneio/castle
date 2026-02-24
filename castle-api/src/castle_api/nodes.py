"""Nodes router — discover and inspect mesh nodes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from castle_api.config import get_registry, settings
from castle_api.mesh import mesh_state
from castle_api.models import ComponentSummary, MeshStatus, NodeDetail, NodeSummary

router = APIRouter(tags=["nodes"])


def _local_node_summary(registry: object) -> NodeSummary:
    """Build a NodeSummary for the local node from the registry."""
    return NodeSummary(
        hostname=registry.node.hostname,
        gateway_port=registry.node.gateway_port,
        deployed_count=len(registry.deployed),
        service_count=sum(1 for d in registry.deployed.values() if d.port is not None),
        is_local=True,
        online=True,
        is_stale=False,
    )


def _remote_node_summary(hostname: str, remote: object) -> NodeSummary:
    """Build a NodeSummary from a RemoteNode."""
    reg = remote.registry
    return NodeSummary(
        hostname=hostname,
        gateway_port=reg.node.gateway_port,
        deployed_count=len(reg.deployed),
        service_count=sum(1 for d in reg.deployed.values() if d.port is not None),
        is_local=False,
        online=remote.online,
        is_stale=remote.is_stale,
        last_seen=remote.last_seen,
    )


def _deployed_to_summaries(registry: object, hostname: str) -> list[ComponentSummary]:
    """Convert deployed components from a registry into ComponentSummary list."""
    summaries = []
    for name, d in registry.deployed.items():
        summaries.append(
            ComponentSummary(
                id=name,
                category="job" if d.schedule else "service",
                description=d.description,
                behavior=d.behavior,
                stack=d.stack,
                runner=d.runner,
                port=d.port,
                health_path=d.health_path,
                proxy_path=d.proxy_path,
                managed=d.managed,
                schedule=d.schedule,
                node=hostname,
            )
        )
    return summaries


@router.get("/mesh/status", response_model=MeshStatus)
def get_mesh_status(request: Request) -> MeshStatus:
    """Get the current state of the mesh coordination layer."""
    mqtt_client = getattr(request.app.state, "mqtt_client", None)
    mdns = getattr(request.app.state, "mdns", None)

    peers = list(mesh_state.all_nodes(include_stale=True).keys())

    return MeshStatus(
        enabled=settings.mqtt_enabled,
        mqtt_connected=mqtt_client.connected if mqtt_client else False,
        mqtt_broker_host=mqtt_client.broker_host if mqtt_client else None,
        mqtt_broker_port=mqtt_client.broker_port if mqtt_client else None,
        mdns_enabled=settings.mdns_enabled,
        peer_count=len(peers),
        peers=peers,
    )


@router.get("/nodes", response_model=list[NodeSummary])
def list_nodes() -> list[NodeSummary]:
    """List all known nodes (local + discovered remote)."""
    registry = get_registry()
    nodes = [_local_node_summary(registry)]

    for hostname, remote in mesh_state.all_nodes(include_stale=True).items():
        nodes.append(_remote_node_summary(hostname, remote))

    return nodes


@router.get("/nodes/{hostname}", response_model=NodeDetail)
def get_node(hostname: str) -> NodeDetail:
    """Get detailed info for a specific node."""
    registry = get_registry()

    # Local node
    if hostname == registry.node.hostname:
        summary = _local_node_summary(registry)
        deployed = _deployed_to_summaries(registry, hostname)
        return NodeDetail(**summary.model_dump(), deployed=deployed)

    # Remote node
    remote = mesh_state.get_node(hostname)
    if remote is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{hostname}' not found",
        )

    summary = _remote_node_summary(hostname, remote)
    deployed = _deployed_to_summaries(remote.registry, hostname)
    return NodeDetail(**summary.model_dump(), deployed=deployed)
