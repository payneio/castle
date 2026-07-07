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
    kind: str | None = None  # derived: service|job|tool|static|reference
    stack: str | None = None
    manager: str | None = None  # systemd|caddy|path|none
    launcher: str | None = None  # python|command|container|compose|node (systemd only)
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
    enabled: bool = True  # declared desired state; `apply` converges to it
    node: str | None = None


class DeploymentDetail(DeploymentSummary):
    """Full detail for a single component, including raw manifest."""

    manifest: dict


class ServiceSummary(BaseModel):
    """Summary of a service — a systemd daemon OR a caddy-served static site.

    Both are "services" (exposed, URL-reachable things); `kind`/`manager`
    distinguish them (service+systemd vs static+caddy).
    """

    id: str
    description: str | None = None
    stack: str | None = None
    kind: str | None = None  # service | static
    manager: str | None = None  # systemd | caddy
    launcher: str | None = None  # python|command|container|compose|node (systemd only)
    run_target: str | None = None  # what it runs: program name, argv, image, …
    port: int | None = None
    health_path: str | None = None
    subdomain: str | None = None  # exposed at <subdomain>.<gateway.domain>, else None
    managed: bool = False
    systemd: SystemdInfo | None = None
    program: str | None = None  # the program this deployment references, if any
    source: str | None = None
    enabled: bool = True  # declared desired state; `apply` converges to it
    node: str | None = None


class ServiceDetail(ServiceSummary):
    """Full detail for a service, including raw manifest."""

    manifest: dict


class JobSummary(BaseModel):
    """Summary of a job (scheduled task)."""

    id: str
    description: str | None = None
    stack: str | None = None
    launcher: str | None = None  # python|command|container|compose|node
    run_target: str | None = None  # what it runs: program name, argv, …
    schedule: str | None = None
    managed: bool = False
    systemd: SystemdInfo | None = None
    program: str | None = None  # the program this deployment references, if any
    source: str | None = None
    enabled: bool = True  # declared desired state; `apply` converges to it
    node: str | None = None


class JobDetail(JobSummary):
    """Full detail for a job, including raw manifest."""

    manifest: dict


class DeploymentRef(BaseModel):
    """A reference to one of a program's deployments (name + its derived kind)."""

    name: str
    kind: str  # service | job | tool | static | reference


class ProgramSummary(BaseModel):
    """Summary of a program (software catalog entry).

    A program has NO kind of its own — it *has deployments*, each with a kind
    (a program can be a tool AND a job). `deployments` is that list.
    """

    id: str
    description: str | None = None
    stack: str | None = None
    version: str | None = None
    source: str | None = None
    repo: str | None = None
    ref: str | None = None
    commands: dict[str, list[list[str]]] | None = None
    system_dependencies: list[str] = []
    installed: bool | None = None
    active: bool | None = None  # uniform lifecycle state (on PATH / running / served)
    actions: list[str] = []
    deployments: list[DeploymentRef] = []  # this program's deployments (name + kind)
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
    # Public exposure via the tunnel: the public URL, or None if this route is
    # LAN-only. Set when the backing service has `public: true`.
    public_url: str | None = None


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
    # Routing/exposure config (editable from the dashboard).
    domain: str | None = None  # acme zone → <service>.<domain>
    public_domain: str | None = None  # tunnel zone → <service>.<public_domain>
    tunnel_id: str | None = None
    tunnel_connected: bool = False  # cloudflared service active


class GatewayConfigRequest(BaseModel):
    """Editable gateway settings (saved to castle.yaml; deploy to apply)."""

    tls: str | None = None
    domain: str | None = None
    public_domain: str | None = None
    tunnel_id: str | None = None


class NodeSummary(BaseModel):
    """Summary of a discovered node in the mesh."""

    hostname: str
    gateway_port: int
    gateway_domain: str | None = None  # acme domain → dashboard at castle.<domain>
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
    connected: bool = False
    nats_url: str | None = None
    mdns_enabled: bool = False
    peer_count: int = 0
    peers: list[str] = []


class ServiceActionResponse(BaseModel):
    """Response from a service management action."""

    program: str
    action: str
    status: str
