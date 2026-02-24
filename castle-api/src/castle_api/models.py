"""Response models for the dashboard API."""

from pydantic import BaseModel


class SystemdInfo(BaseModel):
    """Systemd unit information for a managed component."""

    unit_name: str
    unit_path: str
    timer: bool = False


class ComponentSummary(BaseModel):
    """Summary of a single component."""

    id: str
    description: str | None = None
    behavior: str | None = None
    stack: str | None = None
    runner: str | None = None
    port: int | None = None
    health_path: str | None = None
    proxy_path: str | None = None
    managed: bool = False
    systemd: SystemdInfo | None = None
    version: str | None = None
    source: str | None = None
    system_dependencies: list[str] = []
    schedule: str | None = None
    installed: bool | None = None
    node: str | None = None


class ComponentDetail(ComponentSummary):
    """Full detail for a single component, including raw manifest."""

    manifest: dict


class HealthStatus(BaseModel):
    """Health status of a single component."""

    id: str
    status: str  # "up", "down", "unknown"
    latency_ms: int | None = None


class StatusResponse(BaseModel):
    """Aggregated health status for all exposed components."""

    statuses: list[HealthStatus]


class GatewayRoute(BaseModel):
    """A single route in the gateway's reverse proxy table."""

    path: str
    target_port: int
    component: str
    node: str


class GatewayInfo(BaseModel):
    """Gateway configuration summary."""

    port: int
    hostname: str
    component_count: int
    service_count: int
    managed_count: int
    routes: list[GatewayRoute] = []


class NodeSummary(BaseModel):
    """Summary of a discovered node in the mesh."""

    hostname: str
    gateway_port: int
    deployed_count: int
    service_count: int
    is_local: bool = False
    online: bool = True
    is_stale: bool = False
    last_seen: float | None = None


class NodeDetail(NodeSummary):
    """Full detail for a node, including its deployed components."""

    deployed: list[ComponentSummary] = []


class MeshStatus(BaseModel):
    """Current state of the mesh coordination layer."""

    enabled: bool = False
    mqtt_connected: bool = False
    mqtt_broker_host: str | None = None
    mqtt_broker_port: int | None = None
    mdns_enabled: bool = False
    peer_count: int = 0
    peers: list[str] = []


class ServiceActionResponse(BaseModel):
    """Response from a service management action."""

    component: str
    action: str
    status: str


class ToolSummary(BaseModel):
    """Summary of a single tool."""

    id: str
    description: str | None = None
    source: str | None = None
    version: str | None = None
    runner: str | None = None
    system_dependencies: list[str] = []
    installed: bool = False


class ToolDetail(ToolSummary):
    """Full detail for a single tool, including documentation."""

    docs: str | None = None
