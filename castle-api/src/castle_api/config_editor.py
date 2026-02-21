"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio
import shutil

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_cli.config import load_config, save_config
from castle_cli.manifest import ComponentManifest

from castle_api.config import settings
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


@router.get("", response_model=ConfigResponse)
def get_config() -> ConfigResponse:
    """Get the raw castle.yaml content."""
    config_path = settings.castle_root / "castle.yaml"
    return ConfigResponse(yaml_content=config_path.read_text())


@router.put("", response_model=ConfigSaveResponse)
def save_yaml(request: ConfigSaveRequest) -> ConfigSaveResponse:
    """Validate and save castle.yaml. Does NOT apply changes."""
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
    config_path = settings.castle_root / "castle.yaml"
    backup_path = config_path.with_suffix(".yaml.bak")
    shutil.copy2(config_path, backup_path)
    config_path.write_text(request.yaml_content)

    return ConfigSaveResponse(ok=True, component_count=count, errors=[])


@router.put("/components/{name}")
def save_component(name: str, request: ComponentConfigRequest) -> dict:
    """Update a single component's config in castle.yaml."""
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

    config = load_config(settings.castle_root)
    config.components[name] = ComponentManifest.model_validate(
        {**request.config, "id": name}
    )
    save_config(config)
    return {"ok": True, "component": name}


@router.delete("/components/{name}")
def delete_component(name: str) -> dict:
    """Remove a component from castle.yaml."""
    config = load_config(settings.castle_root)
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
    """Apply config: regenerate systemd units for managed services + reload gateway."""
    config = load_config(settings.castle_root)
    actions: list[str] = []
    errors: list[str] = []

    # Regenerate and restart managed services
    for name in config.managed:
        unit = f"castle-{name}.service"
        ok, output = await _systemctl("restart", unit)
        if ok:
            actions.append(f"Restarted {name}")
        else:
            errors.append(f"Failed to restart {name}: {output}")

    # Reload gateway
    from castle_cli.commands.gateway import _generate_caddyfile
    from castle_cli.config import GENERATED_DIR, ensure_dirs

    ensure_dirs()
    caddyfile_path = GENERATED_DIR / "Caddyfile"
    caddyfile_path.write_text(_generate_caddyfile(config))
    actions.append("Generated Caddyfile")

    if shutil.which("caddy"):
        ok, output = await _run("caddy", "reload",
                                "--config", str(caddyfile_path),
                                "--adapter", "caddyfile")
        if ok:
            actions.append("Reloaded gateway")
        else:
            errors.append(f"Gateway reload failed: {output}")

    await broadcast("config-changed", {"actions": actions})
    return ApplyResponse(ok=len(errors) == 0, actions=actions, errors=errors)


async def _systemctl(action: str, unit: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "systemctl", "--user", action, unit,
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
