"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio
import shutil

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core.config import save_config
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


@router.get("", response_model=ConfigResponse)
def get_config_yaml() -> ConfigResponse:
    """Get the raw castle.yaml content."""
    _require_repo()
    root = get_castle_root()
    config_path = root / "castle.yaml"
    return ConfigResponse(yaml_content=config_path.read_text())


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

    # Validate programs
    prog_count = 0
    programs_data = data.get("programs") or data.get("components") or {}
    for name, comp_data in programs_data.items():
        try:
            comp_data_copy = dict(comp_data) if comp_data else {}
            comp_data_copy["id"] = name
            ProgramSpec.model_validate(comp_data_copy)
            prog_count += 1
        except Exception as e:
            errors.append(f"programs.{name}: {e}")

    # Validate services
    svc_count = 0
    for name, svc_data in data.get("services", {}).items():
        try:
            svc_data_copy = dict(svc_data) if svc_data else {}
            svc_data_copy["id"] = name
            ServiceSpec.model_validate(svc_data_copy)
            svc_count += 1
        except Exception as e:
            errors.append(f"services.{name}: {e}")

    # Validate jobs
    job_count = 0
    for name, job_data in data.get("jobs", {}).items():
        try:
            job_data_copy = dict(job_data) if job_data else {}
            job_data_copy["id"] = name
            JobSpec.model_validate(job_data_copy)
            job_count += 1
        except Exception as e:
            errors.append(f"jobs.{name}: {e}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": errors},
        )

    # Backup and save
    config_path = root / "castle.yaml"
    backup_path = config_path.with_suffix(".yaml.bak")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(request.yaml_content)

    return ConfigSaveResponse(
        ok=True, program_count=prog_count, service_count=svc_count,
        job_count=job_count, errors=[],
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
    config.programs[name] = ProgramSpec.model_validate(
        {**request.config, "id": name}
    )
    save_config(config)
    return {"ok": True, "program": name}


@router.delete("/programs/{name}")
def delete_program(name: str) -> dict:
    """Remove a program from castle.yaml."""
    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program '{name}' not found",
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
    config.services[name] = ServiceSpec.model_validate(
        {**request.config, "id": name}
    )
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
    config.jobs[name] = JobSpec.model_validate(
        {**request.config, "id": name}
    )
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
    """Apply config: restart managed services + regenerate and reload gateway."""
    registry = get_registry()
    actions: list[str] = []
    errors: list[str] = []

    # Restart managed services
    for name, deployed in registry.deployed.items():
        if not deployed.managed:
            continue
        unit = f"castle-{name}.service"
        ok, output = await _systemctl("restart", unit)
        if ok:
            actions.append(f"Restarted {name}")
        else:
            errors.append(f"Failed to restart {name}: {output}")

    # Reload gateway
    from castle_core.config import GENERATED_DIR, ensure_dirs
    from castle_core.generators.caddyfile import generate_caddyfile_from_registry

    ensure_dirs()
    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_path.write_text(generate_caddyfile_from_registry(registry))
    actions.append("Generated Caddyfile")

    if shutil.which("caddy"):
        ok, output = await _run(
            "caddy", "reload", "--config", str(caddyfile_path), "--adapter", "caddyfile"
        )
        if ok:
            actions.append("Reloaded gateway")
        else:
            errors.append(f"Gateway reload failed: {output}")

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


async def _run(*args: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode == 0, (stdout or stderr or b"").decode().strip()
