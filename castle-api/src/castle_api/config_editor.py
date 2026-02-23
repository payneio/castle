"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio
import shutil

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core.config import save_config
from castle_core.manifest import ComponentManifest

from castle_api.config import get_castle_root, get_config, get_registry
from castle_api.stream import broadcast

router = APIRouter(prefix="/config", tags=["config"])


class ConfigResponse(BaseModel):
    yaml_content: str


class ConfigSaveRequest(BaseModel):
    yaml_content: str


class ConfigSaveResponse(BaseModel):
    ok: bool
    component_count: int
    errors: list[str]


class ApplyResponse(BaseModel):
    ok: bool
    actions: list[str]
    errors: list[str]


class ComponentConfigRequest(BaseModel):
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

    if not isinstance(data, dict) or "components" not in data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="YAML must have a 'components' key",
        )

    # Validate each component
    count = 0
    for name, comp_data in data.get("components", {}).items():
        try:
            comp_data_copy = dict(comp_data) if comp_data else {}
            comp_data_copy["id"] = name
            ComponentManifest.model_validate(comp_data_copy)
            count += 1
        except Exception as e:
            errors.append(f"{name}: {e}")

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

    return ConfigSaveResponse(ok=True, component_count=count, errors=[])


@router.put("/components/{name}")
def save_component(name: str, request: ComponentConfigRequest) -> dict:
    """Update a single component's config in castle.yaml."""
    _require_repo()

    # Validate
    try:
        comp_data = dict(request.config)
        comp_data["id"] = name
        ComponentManifest.model_validate(comp_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid component config: {e}",
        )

    config = get_config()
    config.components[name] = ComponentManifest.model_validate(
        {**request.config, "id": name}
    )
    save_config(config)
    return {"ok": True, "component": name}


@router.delete("/components/{name}")
def delete_component(name: str) -> dict:
    """Remove a component from castle.yaml."""
    config = get_config()
    if name not in config.components:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component '{name}' not found",
        )
    del config.components[name]
    save_config(config)
    return {"ok": True, "component": name, "action": "deleted"}


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
