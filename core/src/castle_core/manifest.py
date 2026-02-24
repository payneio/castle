"""Castle manifest models — component specs, service specs, job specs."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

EnvMap = dict[str, str]


class RestartPolicy(str, Enum):
    NO = "no"
    ON_FAILURE = "on-failure"
    ALWAYS = "always"


class TLSMode(str, Enum):
    OFF = "off"
    INTERNAL = "internal"
    LETSENCRYPT = "letsencrypt"


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
    tool: str
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


class RunRemote(RunBase):
    runner: Literal["remote"]
    base_url: str
    health_url: str | None = None


RunSpec = Annotated[
    Union[RunCommand, RunPython, RunContainer, RunNode, RunRemote],
    Field(discriminator="runner"),
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


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str = "1.0.0"
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
# Defaults
# ---------------------


class DefaultsSpec(BaseModel):
    env: EnvMap = Field(default_factory=dict)


# ---------------------
# Component spec — software identity
# ---------------------


class ComponentSpec(BaseModel):
    """Software catalog entry — what exists."""

    id: str = ""
    description: str | None = None

    source: str | None = None
    stack: str | None = None

    install: InstallSpec | None = None
    tool: ToolSpec | None = None
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

    id: str = ""
    component: str | None = None
    description: str | None = None

    run: RunSpec

    expose: ExposeSpec | None = None
    proxy: ProxySpec | None = None
    manage: ManageSpec | None = None
    defaults: DefaultsSpec | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> ServiceSpec:
        if self.manage and self.manage.systemd and self.manage.systemd.enable:
            if self.run.runner == "remote":
                raise ValueError("manage.systemd cannot be enabled for runner=remote.")
        return self


# ---------------------
# Job spec — scheduled task
# ---------------------


class JobSpec(BaseModel):
    """Scheduled task that runs periodically and exits."""

    id: str = ""
    component: str | None = None
    description: str | None = None

    run: RunSpec
    schedule: str
    timezone: str = "America/Los_Angeles"

    manage: ManageSpec | None = None
    defaults: DefaultsSpec | None = None
