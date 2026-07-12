"""Program action endpoints."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core import git
from castle_core.adopt import (
    AdoptError,
    build_adopted_program,
    is_git_url,
    looks_like_program,
)
from castle_core.config import write_program_file
from castle_core.stacks import available_actions, available_stacks, run_action

from castle_api import stream
from castle_api.config import get_config
from castle_api.models import StackStatusModel, ToolStatusModel

if TYPE_CHECKING:
    from castle_core.stack_status import StackStatus

programs_router = APIRouter(tags=["programs"])


@programs_router.get("/stacks")
def list_stacks() -> list[str]:
    """Stack names castle has handlers for — populates the dashboard's stack select
    and keeps it in sync with the backend (no hardcoded frontend list)."""
    return available_stacks()


def _stack_model(st: StackStatus) -> StackStatusModel:
    return StackStatusModel(
        name=st.name,
        tools=[ToolStatusModel(**asdict(t)) for t in st.tools],
        programs=st.programs,
        deployments=st.deployments,
        verbs=st.verbs,
        has_enabled_deployment=st.has_enabled_deployment,
        in_use=st.in_use,
        ok=st.ok,
    )


@programs_router.get("/stacks/status")
def stacks_status() -> list[StackStatusModel]:
    """Every stack's dependency health — tools present-where-needed (run-phase tools
    against the service runtime PATH), who uses it, and the fix for anything missing.
    The Stacks page renders this; `castle stack list` is its CLI twin."""
    from castle_core.stack_status import all_stack_status

    return [_stack_model(s) for s in all_stack_status(get_config())]


@programs_router.get("/stacks/{name}")
def stack_detail(name: str) -> StackStatusModel:
    """One stack's dependency detail (tool versions included)."""
    from castle_core.stack_status import stack_status

    st = stack_status(get_config(), name)
    if st is None:
        raise HTTPException(status_code=404, detail=f"No stack '{name}'")
    return _stack_model(st)


# ---------------------------------------------------------------------------
# Filesystem browse + adopt — powers the dashboard's "Add program" flow, the
# web equivalent of `castle program add <path|git-url>`. Programs live on the
# server's filesystem, so the picker browses the *server's* dirs (a browser's
# native file dialog only sees the client machine).
# ---------------------------------------------------------------------------


@programs_router.get("/fs/browse")
def browse_filesystem(path: str | None = None) -> dict:
    """List sub-directories of ``path`` (default: the repos dir) so the dashboard
    can browse to a program on the server. Directories only; hidden dirs skipped.
    Each entry is flagged when it looks adoptable (a project manifest or git repo).
    """
    config = get_config()
    base = Path(path).expanduser() if path else config.repos_dir
    try:
        base = base.resolve()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Invalid path: {e}")
    if not base.exists():
        raise HTTPException(status_code=404, detail=f"Path does not exist: {base}")
    if not base.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {base}")

    try:
        children = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {base}")

    entries: list[dict] = []
    for child in children:
        if child.name.startswith("."):
            continue
        # A single unreadable child (can't stat/traverse) shouldn't sink the whole
        # listing — skip it rather than 403 the directory.
        try:
            if not child.is_dir():
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_program": looks_like_program(child),
                    "is_git": (child / ".git").exists(),
                }
            )
        except OSError:
            continue

    parent = str(base.parent) if base.parent != base else None
    return {
        "path": str(base),
        "parent": parent,
        "repos_dir": str(config.repos_dir),
        "entries": entries,
    }


class AdoptRequest(BaseModel):
    target: str  # a local server path or a git URL
    name: str | None = None
    description: str = ""


@programs_router.post("/programs/adopt")
def adopt_program(request: AdoptRequest) -> dict:
    """Adopt an existing repo as a program (the web `castle program add`).

    ``target`` is a local server path or a git URL. Writes just the new program's
    file; declaring a deployment (service/job/tool/static) stays a separate step.
    """
    target = request.target.strip()
    if not target:
        raise HTTPException(status_code=422, detail="A path or git URL is required.")

    config = get_config()
    try:
        adopted = build_adopted_program(
            config, target, name=request.name, description=request.description
        )
    except AdoptError as e:
        raise HTTPException(status_code=422, detail=str(e))

    config.programs[adopted.name] = adopted.spec
    write_program_file(config, adopted.name)
    return {
        "ok": True,
        "program": adopted.name,
        "source": adopted.source,
        "stack": adopted.stack,
        "repo": adopted.repo,
        "commands": adopted.commands,
        "is_git_url": is_git_url(target),
    }


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
