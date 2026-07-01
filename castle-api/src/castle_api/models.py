"""Response models for the dashboard API."""

from pydantic import BaseModel


class SystemdInfo(BaseModel):
    """Systemd unit information for a managed component."""

    unit_name: str
    unit_path: str
    timer: bool = False


class DeploymentSummary(BaseModel):
    """Summary of a single component."""

    id: str
    category: str | None = None  # "program", "service", or "job"
    description: str | None = None
    behavior: str | None = None
    stack: str | None = None
    runner: str | None = None
    port: int | None = None
    health_path: str | None = None
    subdomain: str | None = None  # exposed at <subdomain>.<gateway.domain>, else None
    managed: bool = False
    systemd: SystemdInfo | None = None
    version: str | None = None
    source: str | None = None
    repo: str | None = None
    ref: str | None = None
    commands: dict[str, list[list[str]]] | None = None
    system_dependencies: list[str] = []
    schedule: str | None = None
    installed: bool | None = None
    active: bool | None = None  # uniform lifecycle state (on PATH / running / served)
    node: str | None = None


class DeploymentDetail(DeploymentSummary):
    """Full detail for a single component, including raw manifest."""

    manifest: dict


class ServiceSummary(BaseModel):
    """Summary of a service (long-running daemon)."""

    id: str
    description: str | None = None
    stack: str | None = None
    runner: str | None = None
    run_target: str | None = None  # what it runs: program name, argv, image, …
    port: int | None = None
    health_path: str | None = None
    subdomain: str | None = None  # exposed at <subdomain>.<gateway.domain>, else None
    managed: bool = False
    systemd: SystemdInfo | None = None
    program: str | None = None  # the program this deployment references, if any
    source: str | None = None
    node: str | None = None


class ServiceDetail(ServiceSummary):
    """Full detail for a service, including raw manifest."""

    manifest: dict


class JobSummary(BaseModel):
    """Summary of a job (scheduled task)."""

    id: str
    description: str | None = None
    stack: str | None = None
    runner: str | None = None
    run_target: str | None = None  # what it runs: program name, argv, …
    schedule: str | None = None
    managed: bool = False
    systemd: SystemdInfo | None = None
    program: str | None = None  # the program this deployment references, if any
    source: str | None = None
    node: str | None = None


class JobDetail(JobSummary):
    """Full detail for a job, including raw manifest."""

    manifest: dict


class ProgramSummary(BaseModel):
    """Summary of a program (software catalog entry)."""

    id: str
    description: str | None = None
    behavior: str | None = None
    stack: str | None = None
    runner: str | None = None
    version: str | None = None
    source: str | None = None
    repo: str | None = None
    ref: str | None = None
    commands: dict[str, list[list[str]]] | None = None
    system_dependencies: list[str] = []
    installed: bool | None = None
    active: bool | None = None  # uniform lifecycle state (on PATH / running / served)
    actions: list[str] = []
    services: list[str] = []  # services that deploy this program
    jobs: list[str] = []  # jobs that deploy this program
    node: str | None = None


class ProgramDetail(ProgramSummary):
    """Full detail for a program, including raw manifest."""

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
    """One gateway route: a public address mapped to a target.

    kind is `static` (Caddy serves a built dir), `proxy` (reverse-proxy a local
    service), or `remote` (reverse-proxy another node). address is a path prefix
    (`/foo`) or a host (`foo.lan`); target is the serve dir or `host:port`.
    """

    address: str
    kind: str
    target: str
    name: str | None = None
    node: str


class GatewayInfo(BaseModel):
    """Gateway configuration summary."""

    port: int
    hostname: str
    deployment_count: int
    service_count: int
    managed_count: int
    routes: list[GatewayRoute] = []
    # TLS mode: None/"off" → HTTP-only; "acme" → Let's Encrypt wildcard (publicly
    # trusted, no client CA setup) for host routes.
    tls: str | None = None


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

    deployed: list[DeploymentSummary] = []


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

    program: str
    action: str
    status: str
