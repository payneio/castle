"""Nodes router — discover and inspect mesh nodes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from castle_api.config import get_registry, settings
from castle_api.mesh import mesh_state
from castle_api.models import DeploymentSummary, MeshStatus, NodeDetail, NodeSummary

router = APIRouter(tags=["nodes"])


class ConfigValue(BaseModel):
    value: str


@router.get("/mesh/config")
async def list_mesh_config(request: Request) -> dict:
    """List shared-config keys + this node's role (only the authority may write)."""
    client = getattr(request.app.state, "nats_client", None)
    if client is None:
        return {"keys": [], "role": get_registry().node.role}
    return {"keys": await client.list_shared_config(), "role": client.role}


@router.get("/mesh/config/{key:path}")
async def get_mesh_config(key: str, request: Request) -> dict:
    """Read a shared-config value."""
    client = getattr(request.app.state, "nats_client", None)
    value = await client.get_shared_config(key) if client else None
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"config key '{key}' not set")
    return {"key": key, "value": value}


@router.put("/mesh/config/{key:path}")
async def set_mesh_config(key: str, body: ConfigValue, request: Request) -> dict:
    """Write a shared-config value (authority only)."""
    client = getattr(request.app.state, "nats_client", None)
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "mesh not enabled")
    try:
        await client.put_shared_config(key, body.value)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    return {"key": key, "ok": True}


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


def _deployed_to_summaries(registry: object, hostname: str) -> list[DeploymentSummary]:
    """Convert deployed components from a registry into DeploymentSummary list."""
    summaries = []
    for _kind, name, d in registry.all():
        summaries.append(
            DeploymentSummary(
                id=name,
                category="job" if d.schedule else "service",
                description=d.description,
                kind=d.kind,
                stack=d.stack,
                manager=d.manager,
                launcher=d.launcher,
                port=d.port,
                health_path=d.health_path,
                subdomain=d.subdomain,
                managed=d.managed,
                schedule=d.schedule,
                node=hostname,
            )
        )
    return summaries


@router.get("/mesh/status", response_model=MeshStatus)
def get_mesh_status(request: Request) -> MeshStatus:
    """Get the current state of the mesh coordination layer."""
    nats_client = getattr(request.app.state, "nats_client", None)

    peers = list(mesh_state.all_nodes(include_stale=True).keys())

    return MeshStatus(
        enabled=settings.nats_enabled,
        connected=nats_client.connected if nats_client else False,
        nats_url=str(nats_client.servers) if nats_client else None,
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


_TCP_PROTOCOL = {5432: "pg", 7687: "bolt", 1883: "mqtt", 6379: "redis"}


def _endpoints_of_registry(d: object) -> list[dict]:
    """Derive display endpoints from a registry deployment. Mirrors the local
    relations derivation, which gates the http endpoint on being exposed — here the
    registry's `subdomain` is that signal (a reach:off service has none). Without
    this, remote reach:off services show a phantom port (e.g. castle-gateway :9000)."""
    eps: list[dict] = []
    port = getattr(d, "port", None)
    if port is not None and getattr(d, "subdomain", None):
        eps.append({"protocol": "http", "port": port})
    tcp = getattr(d, "tcp_port", None)
    if tcp is not None:
        eps.append({"protocol": _TCP_PROTOCOL.get(tcp, "tcp"), "port": tcp})
    return eps


@router.get("/mesh/deployments")
def mesh_deployments() -> dict:
    """Flattened remote (mesh-discovered) deployments with derived endpoints — the
    data the System Map needs to render other machines. Local node excluded (it's
    already in /graph). Each entry carries its node's `domain` (gateway acme domain)
    so peers can build launch URLs `<subdomain>.<domain>` for exposed apps."""
    out: list[dict] = []
    for hostname, remote in mesh_state.all_nodes(include_stale=True).items():
        domain = getattr(remote.registry.node, "gateway_domain", None)
        for _kind, name, d in remote.registry.all():
            out.append(
                {
                    "name": name,
                    "kind": d.kind,
                    "node": hostname,
                    "domain": domain,
                    "port": d.port,
                    "base_url": getattr(d, "base_url", None),
                    "subdomain": d.subdomain,
                    "endpoints": _endpoints_of_registry(d),
                    "requires": [
                        r.get("ref") for r in (getattr(d, "requires", None) or []) if r.get("ref")
                    ],
                }
            )
    return {"deployments": out}


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
