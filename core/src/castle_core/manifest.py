"""Castle manifest models — program specs, service specs, job specs."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

EnvMap = dict[str, str]


class RestartPolicy(str, Enum):
    NO = "no"
    ON_FAILURE = "on-failure"
    ALWAYS = "always"


class Reach(str, Enum):
    """How far a deployment is exposed — a protocol-agnostic ladder.

    ``off``      → reachable only at its own host:port (no gateway route).
    ``internal`` → reachable at ``<name>.<domain>`` (HTTP via the gateway, or TCP
                   via bind + wildcard DNS).
    ``public``   → *also* projected to the internet (HTTP via the tunnel origin;
                   TCP via ``cloudflared access tcp``). Implies ``internal``.

    Replaces the old ``proxy``/``public`` booleans; ``proxy``/``public`` survive as
    derived read-only accessors and as accepted *legacy input* (normalized below).
    """

    OFF = "off"
    INTERNAL = "internal"
    PUBLIC = "public"


def _reach_from_legacy(data: object, default: Reach) -> object:
    """Map legacy ``proxy``/``public`` booleans on a raw deployment dict to ``reach``.

    Runs as a ``mode="before"`` validator. When ``reach`` is given explicitly it
    wins (legacy keys are dropped); otherwise ``reach`` is derived from the old
    booleans: ``public`` → PUBLIC, ``proxy`` → INTERNAL, else ``default``. Non-dict
    input (e.g. model re-validation) passes through untouched.
    """
    if not isinstance(data, dict):
        return data
    d = dict(data)
    proxy = bool(d.pop("proxy", False))
    public = bool(d.pop("public", False))
    if "reach" not in d:
        if public:
            d["reach"] = Reach.PUBLIC
        elif proxy:
            d["reach"] = Reach.INTERNAL
        else:
            d["reach"] = default
    return d


# ---------------------
# Launch specs — how systemd starts a process (discriminated union on `launcher`)
# ---------------------
#
# A *launcher* is the process-launch mechanism for a systemd-managed deployment.
# It is orthogonal to the deployment's `manager`: only systemd deployments have a
# launcher, and it says only how the process starts — not how it's supervised.
# The non-process managers (caddy/path/none) have no launcher; their fields live
# on the deployment variant itself.


class LaunchBase(BaseModel):
    launcher: str


class RunCommand(LaunchBase):
    launcher: Literal["command"]
    argv: list[str] = Field(min_length=1)


class RunPython(LaunchBase):
    launcher: Literal["python"]
    program: str
    args: list[str] = Field(default_factory=list)


class RunContainer(LaunchBase):
    launcher: Literal["container"]
    image: str
    command: list[str] | None = None
    args: list[str] = Field(default_factory=list)
    ports: dict[int, int] = Field(default_factory=dict)
    volumes: list[str] = Field(default_factory=list)
    env: EnvMap = Field(default_factory=dict)
    workdir: str | None = None
    # Run the container as this uid[:gid] (e.g. "${uid}:${gid}"). Running as the
    # invoking user makes bind-mounted data/secrets/certs readable with no chown —
    # see docs/tcp-exposure.md §4. None → the image's own default user.
    user: str | None = None
    # tmpfs mounts (e.g. ["/var/run/postgresql"]) for image runtime dirs that must
    # be writable when the container runs as a non-default uid.
    tmpfs: list[str] = Field(default_factory=list)


class RunNode(LaunchBase):
    launcher: Literal["node"]
    script: str
    package_manager: Literal["npm", "pnpm", "yarn"] = "pnpm"
    args: list[str] = Field(default_factory=list)


class RunCompose(LaunchBase):
    """A multi-container stack supervised as one unit via ``docker compose``.

    Unlike ``container`` (a single ``docker run``), compose owns the stack's own
    networking, startup ordering, and per-service health — Castle delegates rather
    than reinventing orchestration. The unit runs ``compose up`` attached
    (``Type=simple``) and tears the stack down via a generated ``ExecStop`` (down).
    Env/secrets flow through systemd ``Environment=``/``EnvironmentFile=`` (from
    ``defaults.env``); compose interpolates them from the process environment.
    """

    launcher: Literal["compose"]
    file: str = "docker-compose.yml"  # resolved relative to the program source
    project_name: str | None = None  # ``-p``; defaults to ``castle-<name>``


LaunchSpec = Annotated[
    Union[
        RunCommand,
        RunPython,
        RunContainer,
        RunNode,
        RunCompose,
    ],
    Field(discriminator="launcher"),
]


# ---------------------
# Systemd management
# ---------------------


class ReadinessHttpGet(BaseModel):
    http_get: str
    timeout_seconds: int = 2
    interval_seconds: int = 2
    success_codes: list[int] = Field(default_factory=lambda: [200])


class SystemdSpec(BaseModel):
    enable: bool = True
    user: bool = True
    description: str | None = None
    after: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    wanted_by: list[str] = Field(default_factory=lambda: ["default.target"])
    restart: RestartPolicy = RestartPolicy.ON_FAILURE
    restart_sec: int = 2
    no_new_privileges: bool = True
    readiness: ReadinessHttpGet | None = None
    exec_reload: str | None = None


class ManageSpec(BaseModel):
    systemd: SystemdSpec | None = None


# ---------------------
# Exposure — HTTP (via the gateway) or raw TCP (bind + DNS)
# ---------------------


class HttpInternal(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    unix_socket: str | None = None


class HttpExposeSpec(BaseModel):
    internal: HttpInternal
    health_path: str | None = None


class TlsMaterial(str, Enum):
    """What cert files castle materializes onto a service from the wildcard cert.

    ``off``      → the service does its own TLS (or none); castle stays out of it.
    ``pair``     → cert.pem + key.pem (postgres, redis, most daemons).
    ``combined`` → one file: key+cert concatenated (mongodb, haproxy, …).
    """

    OFF = "off"
    PAIR = "pair"
    COMBINED = "combined"


class TlsSpec(BaseModel):
    """Castle-managed TLS material for a raw-TCP service, cut from the gateway's
    ACME wildcard cert (valid for ``<name>.<domain>``) and refreshed on renewal.
    The service consumes the materialized files via the ``${tls_*}`` placeholders.
    """

    material: TlsMaterial = TlsMaterial.OFF
    # Optional zero-downtime reload argv (a single command) run after the cert is
    # re-materialized on renewal — e.g. ["systemctl", "--user", "reload", "castle-postgres"].
    # Default (None): castle restarts the deployment (fine at a ~60-day cadence).
    reload: list[str] | None = None


class TcpExposeSpec(BaseModel):
    """A raw-TCP service (postgres, redis, …). It doesn't ride the HTTP gateway:
    with ``reach: internal`` it's reachable at ``<name>.<domain>:<port>`` via the
    wildcard DNS record + the bound port (no Caddy route). Publishing the port on
    the LAN is the deployment's own job (a container's ``run.ports``, or a native
    service binding ``0.0.0.0``); castle doesn't rebind it, so there's no bind-host
    field here to imply otherwise. ``tls`` (optional) has castle drop the wildcard
    cert onto the service so it presents a trusted cert for ``<name>.<domain>``.
    """

    port: int = Field(ge=1, le=65535)
    tls: TlsSpec | None = None


class ExposeSpec(BaseModel):
    http: HttpExposeSpec | None = None
    tcp: TcpExposeSpec | None = None

    @model_validator(mode="after")
    def _one_protocol(self) -> ExposeSpec:
        if self.http and self.tcp:
            raise ValueError("a deployment exposes http OR tcp, not both")
        return self


# ---------------------
# Build spec
# ---------------------


class BuildSpec(BaseModel):
    commands: list[list[str]] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


# ---------------------
# Commands spec — per-program dev verb overrides
# ---------------------


class CommandsSpec(BaseModel):
    """Per-program dev verb commands. Each verb is a list of argv lists run in
    sequence. A declared verb overrides the stack default; an absent verb falls
    back to the program's stack handler (if any), else the verb is unavailable.

    This generalizes BuildSpec.commands to the rest of the verb contract, which
    is what lets a wired-in repo with no `stack` declare how it is linted/tested/run.
    """

    model_config = ConfigDict(populate_by_name=True)

    lint: list[list[str]] | None = None
    test: list[list[str]] | None = None
    type_check: list[list[str]] | None = Field(default=None, alias="type-check")
    check: list[list[str]] | None = None
    run: list[list[str]] | None = None
    install: list[list[str]] | None = None
    uninstall: list[list[str]] | None = None

    def for_verb(self, verb: str) -> list[list[str]] | None:
        """Return the declared commands for a verb name (accepts 'type-check')."""
        return getattr(self, verb.replace("-", "_"), None)


# ---------------------
# Capabilities
# ---------------------


class Capability(BaseModel):
    type: str
    name: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)


class Requirement(BaseModel):
    """A precondition — another **deployment** that must exist for this one to be
    *functional* (``ref`` = the target deployment's name). ``bind`` names the env
    var castle projects the target's URL into — env is derived *from* the
    requirement, never scraped back into it.

    A deployment declares these in its ``requires`` list; ``kind`` defaults to
    ``deployment`` (write just ``- ref: foo``). The ``system`` kind is not written
    here — a program's host-package preconditions live in ``system_dependencies``,
    and the relationship model synthesizes ``kind: system`` requirements from it for
    the ``functional?`` check. See docs/relationships.md.
    """

    kind: Literal["system", "deployment"] = "deployment"
    ref: str
    bind: str | None = None


# ---------------------
# Defaults
# ---------------------


class DefaultsSpec(BaseModel):
    env: EnvMap = Field(default_factory=dict)


# ---------------------
# Agent spec — a launchable agent CLI (assistant-agnostic)
# ---------------------


class SessionsSpec(BaseModel):
    """Declarative session-history capability for an agent (optional).

    Lets the dashboard show a unified picker of an agent's *own* past sessions
    without castle knowing anything agent-specific in code: it runs
    ``list_command`` (which must print a JSON array of session objects), reads
    three named fields off each object, and launches ``command`` + ``resume``
    (with ``{id}`` substituted) to reopen one. Field names default to opencode's
    shape and are overridable per agent (dotted paths allowed, e.g.
    ``config_summary.session_id``).
    """

    list_command: list[str]  # argv → JSON array of session objects
    resume: list[str]  # appended to the agent command; "{id}" is substituted
    id_field: str = "id"
    title_field: str = "title"
    time_field: str = "updated"


class AgentSpec(BaseModel):
    """A launchable agent CLI for the dashboard's terminal UX.

    Castle just runs ``command args`` inside a pty at ``cwd``; it never parses
    the agent's output, so any interactive CLI works. This block only names the
    launch — live sessions (list/resume/kill) are a runtime concern, not config.
    """

    command: str
    args: list[str] = Field(default_factory=list)
    description: str | None = None
    cwd: str | None = None  # defaults to the castle repo root when unset
    env: EnvMap = Field(default_factory=dict)
    # Extra args that open the agent's own session browser / continue its last
    # conversation (e.g. ["--resume"] or ["--continue"]). Optional and
    # agent-specific — castle just passes them through. Empty = no such affordance.
    resume_args: list[str] = Field(default_factory=list)
    # Optional: declares how to list + resume the agent's own sessions, so the
    # dashboard can render a unified session picker (see SessionsSpec).
    sessions: SessionsSpec | None = None


# ---------------------
# Program spec — software identity
# ---------------------


class ProgramSpec(BaseModel):
    """Software catalog entry — what exists."""

    id: str = ""
    description: str | None = None
    # A program has NO kind of its own — kind is a *deployment* property. A program
    # is a catalog entry that has 0..N deployments, each with its own kind (see
    # kind_for and CastleConfig.deployments_of).

    source: str | None = None
    stack: str | None = None

    # Wiring in existing repos: clone from `repo` (git URL) at optional `ref`;
    # `source` (when set) is the local working copy and takes precedence.
    repo: str | None = None
    ref: str | None = None

    # Per-program dev verb overrides (declared verbs override the stack default).
    commands: CommandsSpec | None = None

    # Host-package preconditions (apt packages / binaries) intrinsic to this
    # software. The relationship model checks these (`which`/`dpkg`) to derive the
    # `functional?` light. Deployment-to-deployment dependencies are NOT here — they
    # live on the deployment's `requires` (see DeploymentBase). See docs/relationships.md.
    system_dependencies: list[str] = Field(default_factory=list)
    install_extras: list[str] = Field(default_factory=list)
    version: str | None = None
    build: BuildSpec | None = None

    provides: list[Capability] = Field(default_factory=list)
    consumes: list[Capability] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)

    @property
    def source_dir(self) -> str | None:
        """Relative directory for this component's source, or None."""
        if self.source:
            return self.source.rstrip("/")
        return None


# ---------------------
# Deployment specs — a program materialized into the runtime
# ---------------------
#
# A deployment is discriminated on its `manager` — who supervises/realizes it:
#   systemd → a process (or, with a `schedule`, a `.timer`)
#   caddy   → a gateway route serving a static dir (file_server)
#   path    → a CLI installed on PATH (uv tool install)
#   none    → an external reference we only point at (remote)
# The human "kind" (service/job/tool/static/reference) is *derived* from the
# manager (+ schedule presence), never stored — see `kind_for`.


class DeploymentBase(BaseModel):
    """Fields common to every deployment, regardless of manager."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    # The program this deployment materializes. (`component` = legacy alias.)
    program: str | None = Field(
        default=None, validation_alias=AliasChoices("program", "component")
    )
    description: str | None = None
    defaults: DefaultsSpec | None = None
    # Deployment-to-deployment preconditions: other deployments this one needs
    # (e.g. a frontend that requires its API + the supabase substrate). Each entry
    # is `- ref: <deployment>` (+ optional `bind: ENV_VAR` to project the target's
    # URL into env). Drives the relationship graph's edges. See docs/relationships.md.
    requires: list[Requirement] = Field(default_factory=list)
    # Declared on/off state. `castle apply` converges reality to this: enabled
    # deployments are activated (service started, tool installed, route served),
    # disabled ones are deactivated but kept in the catalog. This is *desired
    # state*, not a runtime toggle — the only way to durably stop something.
    enabled: bool = True


class SystemdDeployment(DeploymentBase):
    """A process supervised by systemd — a *service*, or a *job* when scheduled."""

    manager: Literal["systemd"]
    run: LaunchSpec
    # Present → a `.timer` (job); absent → a continuous `.service` (service).
    schedule: str | None = None
    timezone: str = "America/Los_Angeles"
    expose: ExposeSpec | None = None
    # How far this process is exposed (off | internal | public). See `Reach`.
    reach: Reach = Reach.OFF
    manage: ManageSpec | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_reach(cls, data: object) -> object:
        return _reach_from_legacy(data, default=Reach.OFF)

    @model_validator(mode="after")
    def _validate_reach(self) -> SystemdDeployment:
        # An exposed reach needs a port to expose. Without an `expose` block the
        # reach silently no-ops — no route, no subdomain, no tunnel entry — so a
        # typo'd/omitted `expose` reads as success while the service is unreachable.
        # Reject it at load so the mistake surfaces (replaces the old
        # "public requires proxy" guard, now that reach is the canonical field).
        # Static frontends (manager: caddy) are inherently exposed and validated
        # elsewhere; this is a supervised process, which needs an explicit port.
        if self.reach != Reach.OFF and not self.expose:
            raise ValueError(
                f"reach: {self.reach.value} requires an `expose` block "
                "(expose.http or expose.tcp); a port-only process uses reach: off"
            )
        # Public raw-TCP (tunnel + Access) is a later step; guard it explicitly
        # rather than silently no-op'ing when a TCP service asks for it.
        if (
            self.reach == Reach.PUBLIC
            and self.expose
            and self.expose.tcp
            and not self.expose.http
        ):
            raise ValueError(
                "reach: public for a raw-TCP service isn't supported yet "
                "(see docs/tcp-exposure.md step 5); use reach: internal"
            )
        return self

    # Derived, read-only back-compat accessors (not serialized) so existing
    # readers keep working while the stored/authored field is `reach`.
    @property
    def proxy(self) -> bool:
        return self.reach != Reach.OFF

    @property
    def public(self) -> bool:
        return self.reach == Reach.PUBLIC

    @property
    def http_exposed(self) -> bool:
        """Exposed through the HTTP gateway at ``<name>.<domain>`` — the predicate
        for a Caddy route / subdomain. Requires ``reach != off`` *and* an HTTP
        port; a raw-TCP service (``expose.tcp``) is never HTTP-exposed."""
        return self.reach != Reach.OFF and bool(self.expose and self.expose.http)

    @property
    def tcp_port(self) -> int | None:
        """The raw-TCP port this service is exposed on, or None. Reachable at
        ``<name>.<domain>:<port>`` when ``reach != off`` (bind + wildcard DNS)."""
        if self.reach != Reach.OFF and self.expose and self.expose.tcp:
            return self.expose.tcp.port
        return None


class CaddyDeployment(DeploymentBase):
    """A static site served by the gateway (Caddy ``file_server``) — no process.

    The gateway *is* its runtime; it's inherently exposed at its subdomain. ``root``
    is the built dir to serve, relative to the program source (e.g. ``dist``/``public``).
    """

    manager: Literal["caddy"]
    root: str = "dist"
    # A static site is inherently served at its subdomain, so `reach` is
    # `internal` or `public` (never `off`). `public` = also project via the tunnel.
    reach: Reach = Reach.INTERNAL

    @model_validator(mode="before")
    @classmethod
    def _normalize_reach(cls, data: object) -> object:
        return _reach_from_legacy(data, default=Reach.INTERNAL)

    @model_validator(mode="after")
    def _validate_reach(self) -> CaddyDeployment:
        if self.reach == Reach.OFF:
            raise ValueError("a static (caddy) deployment is always served; reach must be internal|public")
        return self

    @property
    def public(self) -> bool:
        return self.reach == Reach.PUBLIC


class PathDeployment(DeploymentBase):
    """A CLI installed on PATH via ``uv tool install`` — no process, no route.

    Lifecycle is install/uninstall (what start/stop/enable/disable map to).
    """

    manager: Literal["path"]


class RemoteDeployment(DeploymentBase):
    """An external service (another node) — we only reference/route it, never run it."""

    manager: Literal["none"]
    base_url: str
    health_url: str | None = None


DeploymentSpec = Annotated[
    Union[SystemdDeployment, CaddyDeployment, PathDeployment, RemoteDeployment],
    Field(discriminator="manager"),
]


def kind_for(spec: DeploymentSpec) -> str:
    """The derived kind of a deployment: service|job|tool|static|reference."""
    if spec.manager == "systemd":
        return "job" if getattr(spec, "schedule", None) else "service"
    return {"caddy": "static", "path": "tool", "none": "reference"}[spec.manager]
