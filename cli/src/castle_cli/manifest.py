"""Castle component manifest — Pydantic models for the component registry."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, computed_field, model_validator

EnvMap = dict[str, str]


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


# ---------------------
# Run specs (discriminated union)
# ---------------------


class RunBase(BaseModel):
    runner: str
    cwd: str | None = None
    env: EnvMap = Field(default_factory=dict)


class RunCommand(RunBase):
    runner: Literal["command"]
    argv: list[str] = Field(min_length=1)


class RunPythonModule(RunBase):
    runner: Literal["python_module"]
    module: str
    args: list[str] = Field(default_factory=list)
    python: str | None = None


class RunPythonUvTool(RunBase):
    runner: Literal["python_uv_tool"]
    tool: str
    args: list[str] = Field(default_factory=list)


class RunContainer(RunBase):
    runner: Literal["container"]
    image: str
    command: list[str] | None = None
    args: list[str] = Field(default_factory=list)
    ports: dict[int, int] = Field(default_factory=dict)
    volumes: list[str] = Field(default_factory=list)
    workdir: str | None = None


class RunNode(RunBase):
    runner: Literal["node"]
    script: str
    package_manager: Literal["npm", "pnpm", "yarn"] = "pnpm"
    args: list[str] = Field(default_factory=list)


class RunRemote(RunBase):
    runner: Literal["remote"]
    base_url: str
    health_url: str | None = None


RunSpec = Annotated[
    Union[RunCommand, RunPythonModule, RunPythonUvTool, RunContainer, RunNode, RunRemote],
    Field(discriminator="runner"),
]


# ---------------------
# Triggers
# ---------------------


class TriggerManual(BaseModel):
    type: Literal["manual"] = "manual"


class TriggerSchedule(BaseModel):
    type: Literal["schedule"] = "schedule"
    cron: str
    timezone: str = "America/Los_Angeles"


class TriggerEvent(BaseModel):
    type: Literal["event"] = "event"
    source: str
    topic: str | None = None
    queue: str | None = None


class TriggerRequest(BaseModel):
    type: Literal["request"] = "request"
    protocol: Literal["http", "https", "grpc"] = "http"


TriggerSpec = Union[TriggerManual, TriggerSchedule, TriggerEvent, TriggerRequest]


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


class ManageSpec(BaseModel):
    systemd: SystemdSpec | None = None


# ---------------------
# Install (PATH shims)
# ---------------------


class PathInstallSpec(BaseModel):
    enable: bool = True
    alias: str | None = None
    shim: bool = True


class InstallSpec(BaseModel):
    path: PathInstallSpec | None = None


# ---------------------
# Tool spec
# ---------------------


class ToolType(str, Enum):
    PYTHON_UV = "python_uv"
    PYTHON_STANDALONE = "python_standalone"
    SCRIPT = "script"


class ToolSpec(BaseModel):
    tool_type: ToolType = ToolType.PYTHON_UV
    category: str | None = None
    version: str = "1.0.0"
    source: str | None = None
    entry_point: str | None = None
    system_dependencies: list[str] = Field(default_factory=list)


# ---------------------
# HTTP exposure + proxy
# ---------------------


class HttpInternal(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    unix_socket: str | None = None


class HttpPublic(BaseModel):
    hostnames: list[str] = Field(min_length=1)
    path_prefix: str = "/"
    tls: TLSMode = TLSMode.INTERNAL


class HttpExposeSpec(BaseModel):
    internal: HttpInternal
    public: HttpPublic | None = None
    health_path: str | None = None


class ExposeSpec(BaseModel):
    http: HttpExposeSpec | None = None


class CaddySpec(BaseModel):
    enable: bool = True
    path_prefix: str | None = None
    extra_snippets: list[str] = Field(default_factory=list)


class ProxySpec(BaseModel):
    caddy: CaddySpec | None = None


# ---------------------
# Build spec
# ---------------------


class BuildSpec(BaseModel):
    commands: list[list[str]] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


# ---------------------
# Capabilities
# ---------------------


class Capability(BaseModel):
    type: str
    name: str | None = None
    meta: dict[str, str] = Field(default_factory=dict)


# ---------------------
# Component manifest
# ---------------------


class ComponentManifest(BaseModel):
    id: str = ""
    name: str | None = None
    description: str | None = None

    run: RunSpec | None = None

    triggers: list[TriggerSpec] = Field(default_factory=list)

    manage: ManageSpec | None = None
    install: InstallSpec | None = None
    tool: ToolSpec | None = None
    expose: ExposeSpec | None = None
    proxy: ProxySpec | None = None
    build: BuildSpec | None = None

    provides: list[Capability] = Field(default_factory=list)
    consumes: list[Capability] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def roles(self) -> list[Role]:
        roles: set[Role] = set()

        if self.run:
            if self.run.runner == "remote":
                roles.add(Role.REMOTE)
            if self.run.runner == "container":
                roles.add(Role.CONTAINERIZED)

        if self.install and self.install.path and self.install.path.enable:
            roles.add(Role.TOOL)

        if self.tool:
            roles.add(Role.TOOL)

        if self.expose and self.expose.http:
            roles.add(Role.SERVICE)

        if (
            self.manage
            and self.manage.systemd
            and self.manage.systemd.enable
            and not (self.expose and self.expose.http)
        ):
            roles.add(Role.WORKER)

        if self.build and (self.build.outputs or self.build.commands):
            roles.add(Role.FRONTEND)

        if any(getattr(t, "type", None) == "schedule" for t in self.triggers):
            roles.add(Role.JOB)

        if not roles:
            roles.add(Role.TOOL)

        return sorted(roles, key=lambda r: r.value)

    @model_validator(mode="after")
    def _basic_consistency(self) -> ComponentManifest:
        if self.manage and self.manage.systemd and self.manage.systemd.enable:
            if self.run and self.run.runner == "remote":
                raise ValueError("manage.systemd cannot be enabled for runner=remote.")
        return self
