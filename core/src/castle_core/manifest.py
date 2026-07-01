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
# Run specs (discriminated union)
# ---------------------


class RunBase(BaseModel):
    runner: str


class RunCommand(RunBase):
    runner: Literal["command"]
    argv: list[str] = Field(min_length=1)


class RunPython(RunBase):
    runner: Literal["python"]
    program: str
    args: list[str] = Field(default_factory=list)


class RunContainer(RunBase):
    runner: Literal["container"]
    image: str
    command: list[str] | None = None
    args: list[str] = Field(default_factory=list)
    ports: dict[int, int] = Field(default_factory=dict)
    volumes: list[str] = Field(default_factory=list)
    env: EnvMap = Field(default_factory=dict)
    workdir: str | None = None


class RunNode(RunBase):
    runner: Literal["node"]
    script: str
    package_manager: Literal["npm", "pnpm", "yarn"] = "pnpm"
    args: list[str] = Field(default_factory=list)


class RunCompose(RunBase):
    """A multi-container stack supervised as one unit via ``docker compose``.

    Unlike ``container`` (a single ``docker run``), compose owns the stack's own
    networking, startup ordering, and per-service health — Castle delegates rather
    than reinventing orchestration. The unit runs ``compose up`` attached
    (``Type=simple``) and tears the stack down via a generated ``ExecStop`` (down).
    Env/secrets flow through systemd ``Environment=``/``EnvironmentFile=`` (from
    ``defaults.env``); compose interpolates them from the process environment.
    """

    runner: Literal["compose"]
    file: str = "docker-compose.yml"  # resolved relative to the program source
    project_name: str | None = None  # ``-p``; defaults to ``castle-<name>``


class RunRemote(RunBase):
    runner: Literal["remote"]
    base_url: str
    health_url: str | None = None


class RunStatic(RunBase):
    """A static site served by the gateway (Caddy ``file_server``), no process.

    Like ``remote``, this is a service with no local process and no systemd unit —
    the gateway *is* its runtime. ``root`` is the built directory to serve, resolved
    relative to the referenced program's source (e.g. ``dist`` or ``public``).
    Building that directory is the program's concern; this only serves it.
    """

    runner: Literal["static"]
    root: str = "dist"  # served dir, relative to the program source


class RunPath(RunBase):
    """A CLI installed on the user's PATH via ``uv tool install`` — no process.

    Like ``remote``/``static`` it has no systemd unit; its manager is **PATH**.
    The referenced program is what gets installed; its lifecycle is
    install/uninstall (which is what start/stop/enable/disable map to).
    """

    runner: Literal["path"]


RunSpec = Annotated[
    Union[
        RunCommand,
        RunPython,
        RunContainer,
        RunNode,
        RunCompose,
        RunRemote,
        RunStatic,
        RunPath,
    ],
    Field(discriminator="runner"),
]


# A deployment's *manager* — who makes the program available and supervises it —
# is determined by its runner. This is the single source of truth; lifecycle,
# deploy, and status all dispatch on it rather than special-casing runners.
#   systemd — a long-running process (or a timer, for jobs)
#   caddy   — a gateway route (file_server for static; reverse_proxy for a port)
#   path    — an installed CLI on PATH (via `uv tool install`)
#   none    — external; we only reference/route it (remote)
_RUNNER_MANAGER: dict[str, str] = {
    "python": "systemd",
    "command": "systemd",
    "container": "systemd",
    "compose": "systemd",
    "node": "systemd",
    "static": "caddy",
    "path": "path",
    "remote": "none",
}


def manager_for(runner: str) -> str:
    """The manager (`systemd`|`caddy`|`path`|`none`) that supervises a runner."""
    return _RUNNER_MANAGER.get(runner, "systemd")


# `behavior` (tool/daemon/frontend) is a *derived* descriptive label, computed
# from how a program is deployed — never stored/edited. A static service → a
# frontend; a path install → a tool; anything else running a process → a daemon.
_RUNNER_BEHAVIOR: dict[str, str] = {"static": "frontend", "path": "tool"}


def behavior_for_runner(runner: str) -> str:
    """The display behavior implied by a service's runner."""
    return _RUNNER_BEHAVIOR.get(runner, "daemon")


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
# Program spec — software identity
# ---------------------


class ProgramSpec(BaseModel):
    """Software catalog entry — what exists."""

    id: str = ""
    description: str | None = None
    behavior: str | None = None

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
# Service spec — long-running daemon
# ---------------------


class ServiceSpec(BaseModel):
    """Long-running daemon deployment config."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    # The program this service deploys. (`component` accepted as a legacy alias.)
    program: str | None = Field(
        default=None, validation_alias=AliasChoices("program", "component")
    )
    description: str | None = None

    run: RunSpec

    expose: ExposeSpec | None = None
    # Expose this service at <service-name>.<gateway.domain> through the gateway
    # (the subdomain is the service name). False → reachable only at its host:port.
    proxy: bool = False
    # Also expose this service to the public internet via the Cloudflare tunnel, at
    # <service-name>.<gateway.public_domain>. Default False — public is opt-in and
    # explicit. Requires proxy (the tunnel projects an already-routed subdomain).
    public: bool = False
    manage: ManageSpec | None = None
    defaults: DefaultsSpec | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> ServiceSpec:
        if self.manage and self.manage.systemd and self.manage.systemd.enable:
            if self.run.runner == "remote":
                raise ValueError("manage.systemd cannot be enabled for runner=remote.")
        # A static service is inherently exposed (that's its purpose); other
        # runners need the proxy checkbox to be routed. Public requires exposure.
        exposed = self.proxy or self.run.runner == "static"
        if self.public and not exposed:
            raise ValueError("public requires the service to be exposed (proxy or static).")
        return self


# ---------------------
# Job spec — scheduled task
# ---------------------


class JobSpec(BaseModel):
    """Scheduled task that runs periodically and exits."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    # The program this job runs. (`component` accepted as a legacy alias.)
    program: str | None = Field(
        default=None, validation_alias=AliasChoices("program", "component")
    )
    description: str | None = None

    run: RunSpec
    schedule: str
    timezone: str = "America/Los_Angeles"

    manage: ManageSpec | None = None
    defaults: DefaultsSpec | None = None
