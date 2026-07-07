"""Apply (converge) API endpoint.

`POST /apply` reconciles the running system to match config — render units/
Caddyfile/tunnel, then activate/restart/deactivate to match. It replaces the old
`/deploy` (+ separate start/enable calls). `?plan=true` returns the diff without
touching anything.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from castle_core.config import CastleDirError
from castle_core.deploy import apply

router = APIRouter(tags=["apply"])


class ApplyRequest(BaseModel):
    """Optional request body for apply."""

    name: str | None = None
    plan: bool = False


class ApplyResponse(BaseModel):
    """The diff a converge enacted (or would enact, for a plan)."""

    status: str
    planned: bool
    changed: bool
    activated: list[str]
    restarted: list[str]
    deactivated: list[str]
    unchanged: list[str]
    messages: list[str]


@router.post("/apply", response_model=ApplyResponse)
def run_apply(request: ApplyRequest | None = None) -> ApplyResponse:
    """Converge the running system to match castle.yaml.

    Renders systemd units + the Caddyfile + tunnel config, then reconciles the
    runtime: activate enabled deployments that are down, restart any whose unit
    changed, deactivate disabled ones. Pass a name to converge one deployment,
    or `plan: true` to compute the diff without changing anything.
    """
    name = request.name if request else None
    plan = request.plan if request else False

    try:
        result = apply(target_name=name, plan=plan)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except CastleDirError as e:
        # A fixable misconfiguration (e.g. data_dir points somewhere unwritable), not a
        # server fault — return the actionable message so the dashboard can show it.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return ApplyResponse(
        status="ok",
        planned=result.planned,
        changed=result.changed,
        activated=result.activated,
        restarted=result.restarted,
        deactivated=result.deactivated,
        unchanged=result.unchanged,
        messages=result.messages,
    )
