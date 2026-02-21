"""Response models for the dashboard API."""

from pydantic import BaseModel


class ComponentSummary(BaseModel):
    """Summary of a single component."""

    id: str
    description: str | None = None
    roles: list[str]
    runner: str | None = None
    port: int | None = None
    health_path: str | None = None
    proxy_path: str | None = None
    managed: bool = False
    category: str | None = None
    version: str | None = None
    tool_type: str | None = None


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


class GatewayInfo(BaseModel):
    """Gateway configuration summary."""

    port: int
    component_count: int
    service_count: int
    managed_count: int


class ServiceActionResponse(BaseModel):
    """Response from a service management action."""

    component: str
    action: str
    status: str
