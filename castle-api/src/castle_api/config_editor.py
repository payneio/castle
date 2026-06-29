"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core.config import (
    CastleConfig,
    GatewayConfig,
    _program_to_yaml_dict,
    _spec_to_yaml_dict,
    load_config,
    save_config,
)
from castle_core.manifest import ProgramSpec, JobSpec, ServiceSpec

from castle_api.config import get_castle_root, get_config, get_registry
from castle_api.stream import broadcast

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    yaml_content: str


class ConfigSaveRequest(BaseModel):
    yaml_content: str


class ConfigSaveResponse(BaseModel):
    ok: bool
    program_count: int
    service_count: int
    job_count: int
    errors: list[str]


class ApplyResponse(BaseModel):
    ok: bool
    actions: list[str]
    errors: list[str]


class ProgramConfigRequest(BaseModel):
    config: dict


class ServiceConfigRequest(BaseModel):
    config: dict


class JobConfigRequest(BaseModel):
    config: dict


def _require_repo() -> None:
    """Raise 503 if repo is not available."""
    if get_castle_root() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Castle repo not available on this node.",
        )


def _aggregate_yaml(config: CastleConfig) -> str:
    """Build a unified virtual castle.yaml from the directory-per-resource config."""
    data: dict = {"gateway": {"port": config.gateway.port}}
    if config.repo:
        data["repo"] = str(config.repo)
    if config.programs:
        data["programs"] = {
            n: _program_to_yaml_dict(s, config) for n, s in config.programs.items()
        }
    if config.services:
        data["services"] = {
            n: _spec_to_yaml_dict(s) for n, s in config.services.items()
        }
    if config.jobs:
        data["jobs"] = {n: _spec_to_yaml_dict(s) for n, s in config.jobs.items()}
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


@router.get("", response_model=ConfigResponse)
def get_config_yaml() -> ConfigResponse:
    """Get a unified virtual castle.yaml aggregated from all resource files."""
    _require_repo()
    root = get_castle_root()
    config = load_config(root)
    return ConfigResponse(yaml_content=_aggregate_yaml(config))


@router.put("", response_model=ConfigSaveResponse)
def save_yaml(request: ConfigSaveRequest) -> ConfigSaveResponse:
    """Validate and save castle.yaml. Does NOT apply changes."""
    _require_repo()
    root = get_castle_root()
    errors: list[str] = []

    # Parse YAML
    try:
        data = yaml.safe_load(request.yaml_content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid YAML: {e}",
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YAML must be a mapping",
        )

    # repo: drives repo-relative source resolution (fall back to existing config)
    repo_path = None
    if data.get("repo"):
        from pathlib import Path

        repo_path = Path(data["repo"]).expanduser()
    else:
        try:
            repo_path = load_config(root).repo
        except Exception:
            repo_path = None

    def _resolve_source(spec: ProgramSpec) -> None:
        from pathlib import Path

        if not spec.source:
            return
        if spec.source.startswith("repo:") and repo_path:
            spec.source = str(repo_path / spec.source[5:])
        elif not Path(spec.source).is_absolute():
            spec.source = str(root / spec.source)

    # Validate programs
    programs: dict[str, ProgramSpec] = {}
    programs_data = data.get("programs") or {}
    for name, comp_data in programs_data.items():
        try:
            comp_data_copy = dict(comp_data) if comp_data else {}
            comp_data_copy["id"] = name
            spec = ProgramSpec.model_validate(comp_data_copy)
            _resolve_source(spec)
            programs[name] = spec
        except Exception as e:
            errors.append(f"programs.{name}: {e}")

    # Validate services
    services: dict[str, ServiceSpec] = {}
    for name, svc_data in data.get("services", {}).items():
        try:
            svc_data_copy = dict(svc_data) if svc_data else {}
            svc_data_copy["id"] = name
            services[name] = ServiceSpec.model_validate(svc_data_copy)
        except Exception as e:
            errors.append(f"services.{name}: {e}")

    # Validate jobs
    jobs: dict[str, JobSpec] = {}
    for name, job_data in data.get("jobs", {}).items():
        try:
            job_data_copy = dict(job_data) if job_data else {}
            job_data_copy["id"] = name
            jobs[name] = JobSpec.model_validate(job_data_copy)
        except Exception as e:
            errors.append(f"jobs.{name}: {e}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": errors},
        )

    prog_count = len(programs)
    svc_count = len(services)
    job_count = len(jobs)

    gateway_data = data.get("gateway", {})
    config = CastleConfig(
        root=root,
        repo=repo_path,
        gateway=GatewayConfig(port=gateway_data.get("port", 9000)),
        programs=programs,
        services=services,
        jobs=jobs,
    )
    save_config(config)

    return ConfigSaveResponse(
        ok=True,
        program_count=prog_count,
        service_count=svc_count,
        job_count=job_count,
        errors=[],
    )


@router.put("/programs/{name}")
def save_program(name: str, request: ProgramConfigRequest) -> dict:
    """Update a single program's config in castle.yaml."""
    _require_repo()

    try:
        prog_data = dict(request.config)
        prog_data["id"] = name
        ProgramSpec.model_validate(prog_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid program config: {e}",
        )

    config = get_config()
    config.programs[name] = ProgramSpec.model_validate({**request.config, "id": name})
    save_config(config)
    return {"ok": True, "program": name}


@router.delete("/programs/{name}")
def delete_program(name: str) -> dict:
    """Remove a program from castle.yaml.

    Refuses if any service or job still references the program — those
    deployments must be removed first so no dangling `program:` ref is left.
    """
    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program '{name}' not found",
        )
    refs = [s for s, spec in config.services.items() if spec.program == name]
    refs += [j for j, spec in config.jobs.items() if spec.program == name]
    if refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Programs with active jobs or services cannot be removed. "
                f"Delete these first: {', '.join(refs)}"
            ),
        )
    del config.programs[name]
    save_config(config)
    return {"ok": True, "program": name, "action": "deleted"}


@router.put("/services/{name}")
def save_service(name: str, request: ServiceConfigRequest) -> dict:
    """Update a single service's config in castle.yaml."""
    _require_repo()

    try:
        svc_data = dict(request.config)
        svc_data["id"] = name
        ServiceSpec.model_validate(svc_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid service config: {e}",
        )

    config = get_config()
    config.services[name] = ServiceSpec.model_validate({**request.config, "id": name})
    save_config(config)
    return {"ok": True, "service": name}


@router.delete("/services/{name}")
def delete_service(name: str) -> dict:
    """Remove a service from castle.yaml."""
    config = get_config()
    if name not in config.services:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{name}' not found",
        )
    del config.services[name]
    save_config(config)
    return {"ok": True, "service": name, "action": "deleted"}


@router.put("/jobs/{name}")
def save_job(name: str, request: JobConfigRequest) -> dict:
    """Update a single job's config in castle.yaml."""
    _require_repo()

    try:
        job_data = dict(request.config)
        job_data["id"] = name
        JobSpec.model_validate(job_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid job config: {e}",
        )

    config = get_config()
    config.jobs[name] = JobSpec.model_validate({**request.config, "id": name})
    save_config(config)
    return {"ok": True, "job": name}


@router.delete("/jobs/{name}")
def delete_job(name: str) -> dict:
    """Remove a job from castle.yaml."""
    config = get_config()
    if name not in config.jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{name}' not found",
        )
    del config.jobs[name]
    save_config(config)
    return {"ok": True, "job": name, "action": "deleted"}


@router.post("/apply", response_model=ApplyResponse)
async def apply_config() -> ApplyResponse:
    """Apply config: rebuild runtime from castle.yaml, then restart services.

    Runs a full ``deploy`` so the registry, systemd units, and Caddyfile are all
    regenerated from the current castle.yaml (and the gateway reloaded) — this is
    what keeps the running config from drifting behind an edit. Then restarts the
    managed services so the freshly written units take effect (``deploy`` only
    daemon-reloads; a running unit keeps its old ExecStart until restarted).
    Scheduled jobs are left alone — applying config shouldn't fire every job.
    """
    from castle_core.deploy import deploy

    actions: list[str] = []
    errors: list[str] = []

    # Rebuild registry + units + Caddyfile from castle.yaml off the event loop
    # (deploy is blocking: it shells out to systemctl and the gateway).
    try:
        result = await asyncio.to_thread(deploy)
    except Exception as e:
        return ApplyResponse(ok=False, actions=actions, errors=[f"Deploy failed: {e}"])
    actions.extend(result.messages)

    # Restart managed services so the new units take effect (skip scheduled jobs).
    registry = result.registry or get_registry()
    for name, deployed in registry.deployed.items():
        if not deployed.managed or deployed.schedule:
            continue
        unit = f"castle-{name}.service"
        ok, output = await _systemctl("restart", unit)
        if ok:
            actions.append(f"Restarted {name}")
        else:
            errors.append(f"Failed to restart {name}: {output}")

    await broadcast("config-changed", {"actions": actions})
    return ApplyResponse(ok=len(errors) == 0, actions=actions, errors=errors)


async def _systemctl(action: str, unit: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "systemctl",
        "--user",
        action,
        unit,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode == 0, (stdout or stderr or b"").decode().strip()
