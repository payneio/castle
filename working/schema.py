from __future__ import annotations

from enum import Enum
from typing import Annotated, Dict, List, Literal, Optional, Set, Union

from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    computed_field,
    model_validator,
)


# -------------------------
# Shared primitives
# -------------------------

EnvMap = Dict[str, str]


class RestartPolicy(str, Enum):
    NO = "no"
    ON_FAILURE = "on-failure"
    ALWAYS = "always"


class TLSMode(str, Enum):
    OFF = "off"
    INTERNAL = "internal"
    LETSENCRYPT = "letsencrypt"


class Role(str, Enum):
    TOOL = "tool"
    SERVICE = "service"
    WORKER = "worker"
    FRONTEND = "frontend"
    JOB = "job"
    REMOTE = "remote"
    CONTAINERIZED = "containerized"


# -------------------------
# Run specs (discriminated union)
# -------------------------

class RunBase(BaseModel):
    runner: str
    cwd: Optional[str] = None
    env: EnvMap = Field(default_factory=dict)


class RunCommand(RunBase):
    runner: Literal["command"]
    argv: List[str] = Field(min_length=1)


class RunPythonModule(RunBase):
    runner: Literal["python_module"]
    module: str
    args: List[str] = Field(default_factory=list)
    python: Optional[str] = None  # e.g. "/path/to/python"


class RunPythonUvTool(RunBase):
    runner: Literal["python_uv_tool"]
    tool: str  # the installed tool name
    args: List[str] = Field(default_factory=list)


class RunContainer(RunBase):
    runner: Literal["container"]
    image: str
    command: Optional[List[str]] = None  # overrides image CMD if provided
    args: List[str] = Field(default_factory=list)
    ports: Dict[int, int] = Field(default_factory=dict)  # container_port -> host_port
    volumes: List[str] = Field(default_factory=list)     # "host:container[:ro]"
    workdir: Optional[str] = None


class RunNode(RunBase):
    runner: Literal["node"]
    script: str  # e.g. "dev", "start", or a file path
    package_manager: Literal["npm", "pnpm", "yarn"] = "pnpm"
    args: List[str] = Field(default_factory=list)


class RunRemote(RunBase):
    runner: Literal["remote"]
    base_url: HttpUrl
    # Optional: metadata for how Castle should treat it
    health_url: Optional[HttpUrl] = None


RunSpec = Annotated[
    Union[RunCommand, RunPythonModule, RunPythonUvTool, RunContainer, RunNode, RunRemote],
    Field(discriminator="runner"),
]


# -------------------------
# Triggers
# -------------------------

class TriggerManual(BaseModel):
    type: Literal["manual"] = "manual"


class TriggerSchedule(BaseModel):
    type: Literal["schedule"] = "schedule"
    # Keep this simple + explicit. You can later add "cron"/"interval".
    cron: str  # e.g. "0 * * * *"
    timezone: str = "America/Los_Angeles"


class TriggerEvent(BaseModel):
    type: Literal["event"] = "event"
    source: str  # e.g. "kafka", "redis", "webhook", "fs"
    topic: Optional[str] = None
    queue: Optional[str] = None


class TriggerRequest(BaseModel):
    type: Literal["request"] = "request"
    protocol: Literal["http", "https", "grpc"] = "http"


TriggerSpec = Union[TriggerManual, TriggerSchedule, TriggerEvent, TriggerRequest]


# -------------------------
# Systemd management intent
# -------------------------

class ReadinessHttpGet(BaseModel):
    http_get: HttpUrl | str  # allow templated strings like "http://127.0.0.1:${PORT}/healthz"
    timeout_seconds: int = 2
    interval_seconds: int = 2
    success_codes: List[int] = Field(default_factory=lambda: [200])


class SystemdSpec(BaseModel):
    enable: bool = True
    user: bool = True

    description: Optional[str] = None
    after: List[str] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    wanted_by: List[str] = Field(default_factory=lambda: ["default.target"])

    restart: RestartPolicy = RestartPolicy.ON_FAILURE
    restart_sec: int = 2

    # Optional hardening knobs (you can expand later)
    no_new_privileges: bool = True

    readiness: Optional[ReadinessHttpGet] = None


class ManageSpec(BaseModel):
    systemd: Optional[SystemdSpec] = None


# -------------------------
# Install intent (PATH shims etc.)
# -------------------------

class PathInstallSpec(BaseModel):
    enable: bool = True
    # If set, Castle creates a shim with this name (e.g. ~/.local/bin/<alias>)
    alias: Optional[str] = None
    # If true, shim forwards args to `castle run <id> ...`
    shim: bool = True


class InstallSpec(BaseModel):
    path: Optional[PathInstallSpec] = None


# -------------------------
# HTTP exposure + proxy intent
# -------------------------

class HttpInternal(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    unix_socket: Optional[str] = None  # e.g. "/run/user/1000/notes.sock"

    @model_validator(mode="after")
    def _exactly_one_target(self):
        # allow either (host+port) or unix_socket
        if self.unix_socket and (self.host or self.port):
            # host/port always exist via defaults; treat unix_socket as alternative
            # if unix_socket is set, we ignore host/port semantically
            return self
        return self


class HttpPublic(BaseModel):
    hostnames: List[str] = Field(min_length=1)
    path_prefix: str = "/"
    tls: TLSMode = TLSMode.INTERNAL


class HttpExposeSpec(BaseModel):
    internal: HttpInternal
    public: Optional[HttpPublic] = None
    health_path: Optional[str] = None  # e.g. "/healthz"


class ExposeSpec(BaseModel):
    http: Optional[HttpExposeSpec] = None
    # Future: cli, grpc, etc.


class CaddySpec(BaseModel):
    enable: bool = True
    # Optional: extra per-component knobs
    extra_snippets: List[str] = Field(default_factory=list)


class ProxySpec(BaseModel):
    caddy: Optional[CaddySpec] = None


# -------------------------
# Build spec (mostly for frontends, but generic)
# -------------------------

class BuildSpec(BaseModel):
    # e.g. ["pnpm", "build"] or ["uv", "run", "python", "-m", "build"]
    commands: List[List[str]] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)  # paths relative to cwd/repo


# -------------------------
# Capabilities (optional, for dependency graph)
# -------------------------

class Capability(BaseModel):
    type: str  # e.g. "http.endpoint", "cli.command", "ui.bundle"
    name: Optional[str] = None
    meta: Dict[str, str] = Field(default_factory=dict)


# -------------------------
# The manifest (source of truth)
# -------------------------

class ComponentManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-_.]{1,63}$")
    name: Optional[str] = None
    description: Optional[str] = None

    run: RunSpec

    triggers: List[TriggerSpec] = Field(default_factory=list)

    manage: Optional[ManageSpec] = None
    install: Optional[InstallSpec] = None
    expose: Optional[ExposeSpec] = None
    proxy: Optional[ProxySpec] = None
    build: Optional[BuildSpec] = None

    provides: List[Capability] = Field(default_factory=list)
    consumes: List[Capability] = Field(default_factory=list)

    tags: List[str] = Field(default_factory=list)

    # ---- Derived ontology ----

    @computed_field
    @property
    def roles(self) -> List[Role]:
        """
        Derive roles purely from declared blocks.
        No 'kind/profile' field required.
        """
        roles: Set[Role] = set()

        # Runner-derived roles
        if self.run.runner == "remote":
            roles.add(Role.REMOTE)
        if self.run.runner == "container":
            roles.add(Role.CONTAINERIZED)

        # Interface / integration-derived roles
        if self.install and self.install.path and self.install.path.enable:
            roles.add(Role.TOOL)

        if self.expose and self.expose.http:
            roles.add(Role.SERVICE)

        # Worker vs Service heuristic:
        # If it's managed (systemd) but not exposed over HTTP, it's worker-ish.
        if (
            self.manage
            and self.manage.systemd
            and self.manage.systemd.enable
            and not (self.expose and self.expose.http)
        ):
            roles.add(Role.WORKER)

        # Frontend heuristic: build outputs present (or node runner + build)
        if self.build and (self.build.outputs or self.build.commands):
            # Avoid labeling everything with build as frontend if it's clearly not;
            # if it's exposing HTTP and has build, that's typically frontend or full-stack,
            # but frontend label is still useful.
            roles.add(Role.FRONTEND)

        # Job heuristic: any schedule trigger
        if any(getattr(t, "type", None) == "schedule" for t in self.triggers):
            roles.add(Role.JOB)

        # Fallback: if nothing else, treat as worker-ish if it’s supervised,
        # otherwise tool-ish if it’s transient. But keep it conservative.
        if not roles:
            roles.add(Role.TOOL)

        return sorted(roles, key=lambda r: r.value)

    # ---- Optional consistency checks ----

    @model_validator(mode="after")
    def _basic_consistency(self):
        # If you declare proxy.caddy, you probably mean to expose HTTP publicly.
        if self.proxy and self.proxy.caddy and self.proxy.caddy.enable:
            if not (self.expose and self.expose.http and self.expose.http.public):
                # keep this as a soft constraint by raising a ValueError;
                # remove if you prefer permissive manifests
                raise ValueError(
                    "proxy.caddy is enabled but expose.http.public is not set. "
                    "Either disable caddy or declare public hostnames."
                )

        # If systemd is enabled, ensure runner isn't something obviously incompatible.
        if self.manage and self.manage.systemd and self.manage.systemd.enable:
            if self.run.runner == "remote":
                raise ValueError("manage.systemd cannot be enabled for runner=remote.")

        return self
