"""Deploy API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from castle_core.deploy import deploy

router = APIRouter(tags=["deploy"])


class DeployRequest(BaseModel):
    """Optional request body for deploy."""

    name: str | None = None


class DeployResponse(BaseModel):
    """Response from a deploy operation."""

    status: str
    deployed_count: int
    messages: list[str]


@router.post("/deploy", response_model=DeployResponse)
def run_deploy(request: DeployRequest | None = None) -> DeployResponse:
    """Deploy services and jobs from castle.yaml to runtime.

    Resolves env vars and secrets, generates systemd units and Caddyfile,
    copies frontend build outputs, and reloads systemd.

    Optionally pass a name to deploy a single service or job.
    """
    target_name = request.name if request else None

    try:
        result = deploy(target_name=target_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return DeployResponse(
        status="ok",
        deployed_count=result.deployed_count,
        messages=result.messages,
    )