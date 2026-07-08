"""Config editor — read, validate, save, and apply castle.yaml changes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel

from castle_core.config import (
    KINDS,
    CastleConfig,
    _DEPLOYMENT_ADAPTER,
    _program_to_yaml_dict,
    _spec_to_yaml_dict,
    load_config,
    parse_gateway,
    save_config,
    write_deployment_file,
    write_program_file,
)
from castle_core.manifest import ProgramSpec, kind_for

from castle_api.config import get_castle_root, get_config
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
    if config.role and config.role != "follower":
        data["role"] = config.role
    # `secrets:` isn't modeled on CastleConfig — surface it from the raw file so the
    # aggregate view/round-trip includes it.
    try:
        raw = yaml.safe_load((config.root / "castle.yaml").read_text()) or {}
        if raw.get("secrets"):
            data["secrets"] = raw["secrets"]
    except Exception:
        pass
    if config.programs:
        data["programs"] = {
            n: _program_to_yaml_dict(s, config) for n, s in config.programs.items()
        }
    deps = {n: _spec_to_yaml_dict(s) for _k, n, s in config.all_deployments()}
    if deps:
        data["deployments"] = deps
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

    # Validate deployments (a flat name→spec map in the manager-discriminated shape).
    deployments = {}
    for name, dep_data in (data.get("deployments") or {}).items():
        try:
            dep_copy = dict(dep_data) if dep_data else {}
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

    config = CastleConfig(
        root=root,
        repo=repo_path,
        # Parse the FULL gateway block (tls/domain/tunnel/cert_hook/…), not just
        # port — otherwise a whole-file save silently wipes the gateway config.
        gateway=parse_gateway(data.get("gateway", {})),
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
    """Update a single program's config in castle.yaml (PATCH semantics).

    Like deployments: the incoming config is shallow-merged over the existing
    program spec, so a partial save can't drop source/stack/commands/build/… that
    the client didn't send. Omitted keys are preserved; an explicit ``null`` clears.
    """
    _require_repo()
    config = get_config()
    incoming = dict(request.config)

    if name in config.programs:
        base = config.programs[name].model_dump(mode="json", exclude_none=True)
        merged = {**base, **incoming, "id": name}
        merged = {k: v for k, v in merged.items() if v is not None}
    else:
        merged = {**incoming, "id": name}

    try:
        spec = ProgramSpec.model_validate(merged)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid program config: {e}",
        )

    config.programs[name] = spec
    write_program_file(config, name)  # PATCH: only this program file
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
    refs = [(k, d) for k, d, spec in config.all_deployments() if spec.program == name]
    if refs and not cascade:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{name}' still has deployments ({', '.join(d for _k, d in refs)}). "
                "Delete them first, or pass cascade=true to remove them too."
            ),
        )

    removed: list[str] = []
    if refs:
        from castle_core.lifecycle import deactivate

        for kind, ref in refs:
            # Best-effort teardown (uninstall/stop/disable); still remove the config
            # even if the runtime is already gone.
            try:
                await deactivate(ref, kind, config, config.root)
            except Exception:
                pass
            del config.store_for(kind)[ref]
            write_deployment_file(config, kind, ref)  # unlinks the removed deployment
            removed.append(ref)

    del config.programs[name]
    write_program_file(config, name)  # unlinks the program file only

    if removed:
        # Converge the runtime: prune any orphan units and regenerate the Caddyfile
        # (dropping static routes), then reload the gateway.
        from castle_core.deploy import deploy

        try:
            deploy()
        except Exception:
            pass

    return {
        "ok": True,
        "program": name,
        "action": "deleted",
        "removed_deployments": removed,
    }


def _save_deployment(name: str, config_dict: dict, kind: str | None = None) -> dict:
    """Create/update a deployment (any manager) with PATCH semantics.

    The incoming config is shallow-merged over the existing spec, so a save can
    never silently drop a field the client didn't send (the astro/postgres bug):
    a present key replaces wholesale, an **omitted** key is preserved, and an
    explicit ``null`` clears the key (back to its default). On CREATE there's no
    base, so the incoming config stands alone.

    ``kind`` pins the twin this save targets — a kind-scoped endpoint
    (``/services|/jobs|/tools|/static``) passes it so a partial patch to a
    ``backup`` service can never bleed into a ``backup`` job/tool sharing the
    name. The kind-agnostic ``/deployments/{name}`` leaves it None and infers.
    """
    _require_repo()
    config = get_config()
    incoming = dict(config_dict)

    # Resolve the (name, kind) this save targets. An explicit kind is
    # authoritative (kind-scoped endpoint). Otherwise: a partial patch (e.g. just
    # {reach: off}) has no manager, so we can't derive kind from it — prefer the
    # existing same-named deployment when there's exactly one; else derive the
    # kind from the incoming spec (a create, or disambiguating a shared name).
    named = config.deployments_named(name)
    existing = None
    if kind is not None:
        existing = config.deployment(kind, name)
    elif len(named) == 1:
        existing = named[0][1]
    else:
        try:
            probe = _DEPLOYMENT_ADAPTER.validate_python({**incoming, "id": name})
            existing = config.deployment(kind_for(probe), name)
        except Exception:
            existing = None

    if existing is not None:
        base = existing.model_dump(mode="json", exclude_none=True)
        merged = {**base, **incoming, "id": name}
        # An explicit null means "clear" — drop the key so its default applies.
        merged = {k: v for k, v in merged.items() if v is not None}
    else:
        merged = {**incoming, "id": name}
        # On CREATE with no description, inherit the referenced program's.
        if not merged.get("description"):
            prog = merged.get("program")
            if prog and prog in config.programs and config.programs[prog].description:
                merged["description"] = config.programs[prog].description

    try:
        dep = _DEPLOYMENT_ADAPTER.validate_python(merged)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid deployment config: {e}",
        )
    target_kind = kind_for(dep)
    # A field edit that changes the derived kind (e.g. adds a schedule) moves the
    # spec to the new store; drop the stale entry under the requested kind.
    if kind is not None and target_kind != kind:
        config.store_for(kind).pop(name, None)
        write_deployment_file(config, kind, name)  # spec now absent → unlinks old file
    config.store_for(target_kind)[name] = dep
    write_deployment_file(config, target_kind, name)  # PATCH: only this file
    return {"ok": True, "deployment": name}


def _delete_deployment(name: str, kind: str | None = None) -> dict:
    """Remove a deployment. A kind-scoped delete drops only that twin; the
    kind-agnostic path removes every kind sharing the name."""
    config = get_config()
    removed_kinds = []
    kinds = (kind,) if kind is not None else KINDS
    for k in kinds:
        if name in config.store_for(k):
            del config.store_for(k)[name]
            removed_kinds.append(k)
    if not removed_kinds:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{name}' not found",
        )
    for k in removed_kinds:
        write_deployment_file(config, k, name)  # spec absent → unlinks
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


class EnabledRequest(BaseModel):
    enabled: bool


@router.put("/deployments/{name}/enabled")
def set_deployment_enabled(name: str, request: EnabledRequest) -> dict:
    """Set a deployment's declared `enabled` state (desired on/off).

    Edits config only — the caller runs `POST /apply` to converge. Keeps the
    declarative flow: change what you want, then apply.
    """
    config = get_config()
    deps = config.deployments_named(name)
    if not deps:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{name}' not found",
        )
    # A name may span kinds — toggle all of them together.
    for kind, dep in deps:
        dep.enabled = request.enabled
        write_deployment_file(config, kind, name)
    return {"ok": True, "deployment": name, "enabled": request.enabled}


# Kind-scoped endpoints — pin the twin so a save/delete can't hit a same-named
# deployment of another kind (a `backup` service vs job vs tool).
@router.put("/services/{name}")
def save_service(name: str, request: ServiceConfigRequest) -> dict:
    """Create/update the *service* named `name`."""
    return _save_deployment(name, request.config, kind="service")


@router.delete("/services/{name}")
def delete_service(name: str) -> dict:
    return _delete_deployment(name, kind="service")


@router.put("/jobs/{name}")
def save_job(name: str, request: JobConfigRequest) -> dict:
    """Create/update the *job* named `name`."""
    return _save_deployment(name, request.config, kind="job")


@router.delete("/jobs/{name}")
def delete_job(name: str) -> dict:
    return _delete_deployment(name, kind="job")


@router.put("/tools/{name}")
def save_tool(name: str, request: ServiceConfigRequest) -> dict:
    """Create/update the *tool* named `name`."""
    return _save_deployment(name, request.config, kind="tool")


@router.delete("/tools/{name}")
def delete_tool(name: str) -> dict:
    return _delete_deployment(name, kind="tool")


@router.post("/tools/{name}/schema")
async def generate_tool_schema(
    name: str, deep: bool = False, assist: str | None = None
) -> dict:
    """Generate a *draft* tool-call schema (neutral core) from the tool's ``--help``.

    Not saved — the client reviews/edits it and persists via ``PUT
    /config/tools/{name}`` (the schema rides in the deployment config as
    ``tool_schema``). Two modes:

    * default (``assist`` unset) — deterministic: parse ``--help``. ``deep`` walks
      subcommands. 422 if the tool isn't installed / emits no help.
    * ``assist=llm`` — send the recursive ``--help`` to the litellm proxy for a
      structured schema (the escape hatch for subcommand trees the parser can only
      render as a ``command`` string). 503 if LLM assist is disabled; 502 on an
      upstream/validation failure.
    """
    from castle_core.tool_schema import (
        ToolSchemaError,
        collect_tool_help,
        derive_tool_schema,
    )

    config = get_config()
    if config.deployment("tool", name) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}' not found",
        )

    if assist == "llm":
        from castle_api.config import settings
        from castle_api.llm import LLMAssistError, generate_tool_schema_llm

        if not settings.llm_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LLM assist is disabled (set CASTLE_API_LLM_ENABLED=true).",
            )
        try:
            help_text = collect_tool_help(config, name)
        except ToolSchemaError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
            )
        try:
            schema = await generate_tool_schema_llm(help_text, name)
        except LLMAssistError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
            )
        return {"ok": True, "schema": schema, "assist": "llm"}

    try:
        schema = derive_tool_schema(config, name, deep=deep)
    except ToolSchemaError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    return {"ok": True, "schema": schema}


@router.post("/tools/schema/validate")
def validate_tool_schema_endpoint(core: dict = Body(...)) -> dict:
    """Deterministically validate a tool-call schema core (no LLM) — the shape and
    that ``parameters`` is a valid JSON Schema. Lets the UI check a hand-edited
    schema. Returns ``{valid, errors}``."""
    from castle_core.tool_schema import validate_tool_schema_core

    errors = validate_tool_schema_core(core)
    return {"valid": not errors, "errors": errors}


@router.put("/static/{name}")
def save_static(name: str, request: ServiceConfigRequest) -> dict:
    """Create/update the *static* frontend named `name`."""
    return _save_deployment(name, request.config, kind="static")


@router.delete("/static/{name}")
def delete_static(name: str) -> dict:
    return _delete_deployment(name, kind="static")


@router.put("/references/{name}")
def save_reference(name: str, request: ServiceConfigRequest) -> dict:
    """Create/update an external *reference* (manager: none, base_url) — an
    endpoint castle doesn't run (a SaaS API, a remote/external service)."""
    return _save_deployment(name, request.config, kind="reference")


@router.delete("/references/{name}")
def delete_reference(name: str) -> dict:
    return _delete_deployment(name, kind="reference")


@router.post("/apply", response_model=ApplyResponse)
async def apply_config() -> ApplyResponse:
    """Converge the running system to match castle.yaml (a thin wrapper on core
    ``apply``). Renders units/Caddyfile/tunnel, then reconciles the runtime —
    activating what's enabled and down, restarting only what changed, deactivating
    the disabled. Kept as ``/config/apply`` for compatibility; ``/apply`` exposes
    the same converge with per-deployment targeting and ``--plan``.
    """
    from castle_core.deploy import apply

    # apply is blocking (systemctl + gateway reload) — run off the event loop.
    try:
        result = await asyncio.to_thread(apply)
    except Exception as e:
        return ApplyResponse(ok=False, actions=[], errors=[f"Apply failed: {e}"])

    actions: list[str] = []
    for verb, names in (
        ("Activated", result.activated),
        ("Restarted", result.restarted),
        ("Deactivated", result.deactivated),
    ):
        if names:
            actions.append(f"{verb} {', '.join(sorted(names))}")
    if not result.changed:
        actions.append("Already converged — nothing to do")

    await broadcast("config-changed", {"actions": actions})
    return ApplyResponse(ok=True, actions=actions, errors=[])


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
