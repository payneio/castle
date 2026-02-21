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
    roles: list[str]
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


class ToolSummary(BaseModel):
    """Summary of a single tool."""

    id: str
    description: str | None = None
    source: str | None = None
    version: str | None = None
    runner: str | None = None
    system_dependencies: list[str] = []
    installed: bool = False


class ToolCategory(BaseModel):
    """Tools grouped by category."""

    name: str
    tools: list[ToolSummary]


class ToolDetail(ToolSummary):
    """Full detail for a single tool, including documentation."""

    docs: str | None = None
