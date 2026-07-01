"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core.config import (
    CastleConfig,
    GatewayConfig,
    _DEPLOYMENT_ADAPTER,
    _normalize_deployment_dict,
    _program_to_yaml_dict,
    _spec_to_yaml_dict,
    load_config,
    save_config,
)
from castle_core.manifest import ProgramSpec, kind_for

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


def _require_repo() -> Path:
    """Return the castle repo root, or raise 503 if it's not available."""
    root = get_castle_root()
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Castle repo not available on this node.",
        )
    return root


def _aggregate_yaml(config: CastleConfig) -> str:
    """Build a unified virtual castle.yaml from the directory-per-resource config."""
    data: dict = {"gateway": {"port": config.gateway.port}}
    if config.repo:
        data["repo"] = str(config.repo)
    if config.programs:
        data["programs"] = {
            n: _program_to_yaml_dict(s, config) for n, s in config.programs.items()
        }
    if config.deployments:
        data["deployments"] = {
            n: _spec_to_yaml_dict(s) for n, s in config.deployments.items()
        }
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


@router.get("", response_model=ConfigResponse)
def get_config_yaml() -> ConfigResponse:
    """Get a unified virtual castle.yaml aggregated from all resource files."""
    root = _require_repo()
    config = load_config(root)
    return ConfigResponse(yaml_content=_aggregate_yaml(config))


@router.put("", response_model=ConfigSaveResponse)
def save_yaml(request: ConfigSaveRequest) -> ConfigSaveResponse:
    """Validate and save castle.yaml. Does NOT apply changes."""
    root = _require_repo()
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
        repo_path = Path(data["repo"]).expanduser()
    else:
        try:
            repo_path = load_config(root).repo
        except Exception:
            repo_path = None

    def _resolve_source(spec: ProgramSpec) -> None:
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

    # Validate deployments (accepting a legacy services:/jobs: split too, which
    # the normalizer folds into the single manager-discriminated collection).
    deployments = {}
    raw_deps: dict = dict(data.get("deployments") or {})
    for legacy in ("services", "jobs"):
        raw_deps.update(data.get(legacy) or {})
    for name, dep_data in raw_deps.items():
        try:
            dep_copy = _normalize_deployment_dict(dict(dep_data) if dep_data else {})
            dep_copy = dict(dep_copy)
            dep_copy["id"] = name
            deployments[name] = _DEPLOYMENT_ADAPTER.validate_python(dep_copy)
        except Exception as e:
            errors.append(f"deployments.{name}: {e}")

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": errors},
        )

    prog_count = len(programs)
    svc_count = sum(1 for d in deployments.values() if kind_for(d) == "service")
    job_count = sum(1 for d in deployments.values() if kind_for(d) == "job")

    gateway_data = data.get("gateway", {})
    config = CastleConfig(
        root=root,
        repo=repo_path,
        gateway=GatewayConfig(port=gateway_data.get("port", 9000)),
        programs=programs,
        deployments=deployments,
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
async def delete_program(name: str, cascade: bool = False) -> dict:
    """Remove a program from castle.yaml.

    Without ``cascade``, refuses (409) if any deployment still references the
    program. With ``cascade=true`` it first tears down and removes those
    deployments — dispatched by manager: uninstall a tool from PATH, stop+disable
    a service or job, drop a static route — so nothing is left running, installed,
    or served, then removes the program. A program and its 1:1 tool/static
    deployment are one thing to the user, so this makes "Delete" just work.
    """
    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Program '{name}' not found",
        )
    refs = [d for d, spec in config.deployments.items() if spec.program == name]
    if refs and not cascade:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{name}' still has deployments ({', '.join(refs)}). "
                "Delete them first, or pass cascade=true to remove them too."
            ),
        )

    removed: list[str] = []
    if refs:
        from castle_core.lifecycle import deactivate

        for ref in refs:
            # Best-effort teardown (uninstall/stop/disable); still remove the config
            # even if the runtime is already gone.
            try:
                await deactivate(ref, config, config.root)
            except Exception:
                pass
            del config.deployments[ref]
            removed.append(ref)

    del config.programs[name]
    save_config(config)

    if removed:
        # Converge the runtime: prune any orphan units and regenerate the Caddyfile
        # (dropping static routes), then reload the gateway.
        from castle_core.deploy import deploy

        try:
            deploy()
        except Exception:
            pass

    return {"ok": True, "program": name, "action": "deleted", "removed_deployments": removed}


def _save_deployment(name: str, config_dict: dict) -> dict:
    """Validate a deployment (any manager) and persist it to config.deployments."""
    _require_repo()
    config = get_config()
    config_dict = dict(config_dict)

    # On CREATE (a new deployment) with no description of its own, inherit the
    # referenced program's description — a deployment reads as its program by
    # default. Edits keep whatever the user set (including a cleared field).
    if name not in config.deployments and not config_dict.get("description"):
        prog = config_dict.get("program")
        if prog and prog in config.programs and config.programs[prog].description:
            config_dict["description"] = config.programs[prog].description

    try:
        dep = _DEPLOYMENT_ADAPTER.validate_python(
            _normalize_deployment_dict({**config_dict, "id": name})
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid deployment config: {e}",
        )
    config.deployments[name] = dep
    save_config(config)
    return {"ok": True, "deployment": name}


def _delete_deployment(name: str) -> dict:
    config = get_config()
    if name not in config.deployments:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{name}' not found",
        )
    del config.deployments[name]
    save_config(config)
    return {"ok": True, "deployment": name, "action": "deleted"}


# The deployment endpoints — `deployments` is canonical; `services`/`jobs` remain
# as aliases (the kind is derived, so all three target the one collection).
@router.put("/deployments/{name}")
def save_deployment(name: str, request: ServiceConfigRequest) -> dict:
    """Create/update a deployment of any kind (service/job/tool/static)."""
    return _save_deployment(name, request.config)


@router.delete("/deployments/{name}")
def delete_deployment(name: str) -> dict:
    return _delete_deployment(name)


@router.put("/services/{name}")
def save_service(name: str, request: ServiceConfigRequest) -> dict:
    """Alias of PUT /deployments/{name} (kept for the existing dashboard)."""
    return _save_deployment(name, request.config)


@router.delete("/services/{name}")
def delete_service(name: str) -> dict:
    return _delete_deployment(name)


@router.put("/jobs/{name}")
def save_job(name: str, request: JobConfigRequest) -> dict:
    """Alias of PUT /deployments/{name} (kept for the existing dashboard)."""
    return _save_deployment(name, request.config)


@router.delete("/jobs/{name}")
def delete_job(name: str) -> dict:
    return _delete_deployment(name)


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
