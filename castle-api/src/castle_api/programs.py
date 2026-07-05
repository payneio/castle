"""Program action endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, status

from castle_core import git
from castle_core.stacks import available_actions, available_stacks, run_action

from castle_api import stream
from castle_api.config import get_config

programs_router = APIRouter(tags=["programs"])


@programs_router.get("/stacks")
def list_stacks() -> list[str]:
    """Stack names castle has handlers for — populates the dashboard's stack select
    and keeps it in sync with the backend (no hardcoded frontend list)."""
    return available_stacks()


# ---------------------------------------------------------------------------
# Git sync — pull a program's source working copy up to date (pull only; no
# build/apply/restart — converge stays an explicit, separate step). Declared
# BEFORE the generic /{action} route below so the literal `git`/`sync` segments
# win over the `{action}` path param (Starlette matches in declaration order).
# ---------------------------------------------------------------------------


def _program_source(name: str):
    """The (program, config) for a named program, or raise the standard 404/400s."""
    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found"
        )
    return config.programs[name], config


@programs_router.get("/programs/{name}/git")
def program_git_status(name: str) -> dict:
    """Git status of a program's working copy (branch, dirty, ahead/behind).

    Fetches from the remote first so ``behind`` is current. A program with no
    source or a non-git source returns a benign ``{"is_repo": false}`` (not an
    error) so the dashboard can simply hide the sync control."""
    comp, config = _program_source(name)
    if not comp.source:
        return {"is_repo": False}
    out = asdict(git.git_status(comp.source, fetch=True))
    # Repo context: which repo this program's source lives in and who else shares it
    # (a monorepo). Sync is a repo operation — the UI labels it and lists siblings.
    from castle_core.relations import derive_repos

    for key, repo in derive_repos(config).items():
        if name in repo.programs:
            out["repo"] = {
                "key": key,
                "programs": repo.programs,
                "multi": repo.multi,
                "deployments": repo.deployments,
            }
            break
    return out


@programs_router.post("/programs/{name}/sync")
async def program_sync(name: str) -> dict:
    """Fast-forward a program's working copy (``git pull --ff-only``).

    Pull-only: it updates the source on disk and reports which deployments may now
    need a restart/apply, but does not build, apply, or restart anything itself."""
    comp, config = _program_source(name)
    if not comp.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no source directory")
    if not git.is_git_repo(comp.source):
        raise HTTPException(
            status_code=400, detail=f"'{name}' source is not a git repository"
        )

    before = git.head(comp.source)
    ok, output = git.pull(comp.source)
    if not ok:
        raise HTTPException(status_code=500, detail=output or "git pull failed")

    pulled = git.head(comp.source) != before
    deployments = [dname for dname, _ in config.deployments_of(name)]
    if pulled:
        # Nudge other clients to refresh this program's git status.
        await stream.broadcast(
            "program-sync", {"program": name, "deployments": deployments}
        )

    return {
        "program": name,
        "status": "ok",
        "output": output,
        "pulled": pulled,
        "deployments": deployments if pulled else [],
    }


# ---------------------------------------------------------------------------
# Unified program action endpoint
# ---------------------------------------------------------------------------

# Dev verbs only. Activation (install/uninstall of tools/statics) is convergence:
# it happens through `POST /apply`, not as a program action.
_VALID_ACTIONS = {
    "build",
    "test",
    "lint",
    "type-check",
    "check",
}


@programs_router.post("/programs/{name}/{action}")
async def program_action(name: str, action: str) -> dict:
    """Run a lifecycle action on a program.

    Resolution-aware: a declared `commands:` entry overrides the stack default,
    so a program with no stack can still be linted/tested/built/installed.
    """
    if action not in _VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    config = get_config()
    if name not in config.programs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"'{name}' not found"
        )

    comp = config.programs[name]
    if not comp.source:
        raise HTTPException(status_code=400, detail=f"'{name}' has no source directory")

    if action not in available_actions(comp):
        raise HTTPException(
            status_code=400,
            detail=f"Action '{action}' not available for '{name}' "
            f"(no declared command and no stack handler provides it)",
        )

    result = await run_action(action, name, comp, config.root)

    if result.status != "ok":
        raise HTTPException(status_code=500, detail=result.output or f"{action} failed")

    return {
        "program": result.program,
        "action": result.action,
        "status": result.status,
        "output": result.output,
    }
