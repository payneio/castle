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
# HTTP exposure + proxy
# ---------------------


class HttpInternal(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    unix_socket: str | None = None


class HttpExposeSpec(BaseModel):
    internal: HttpInternal
    health_path: str | None = None


class ExposeSpec(BaseModel):
    http: HttpExposeSpec | None = None


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
    # Route <name>.<gateway.domain> to this process. False → host:port only.
    proxy: bool = False
    # Also publish to the public internet via the Cloudflare tunnel, at
    # <name>.<gateway.public_domain>. Opt-in; requires `proxy`.
    public: bool = False
    manage: ManageSpec | None = None

    @model_validator(mode="after")
    def _validate(self) -> SystemdDeployment:
        if self.public and not self.proxy:
            raise ValueError("public requires proxy (an exposed process).")
        return self


class CaddyDeployment(DeploymentBase):
    """A static site served by the gateway (Caddy ``file_server``) — no process.

    The gateway *is* its runtime; it's inherently exposed at its subdomain. ``root``
    is the built dir to serve, relative to the program source (e.g. ``dist``/``public``).
    """

    manager: Literal["caddy"]
    root: str = "dist"
    # Inherently exposed at its subdomain; `public` = also project via the tunnel.
    public: bool = False


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
