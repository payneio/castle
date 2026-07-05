"""Repo endpoints — a repo (git working copy) is the unit of sync. A monorepo backs
several programs; an adopted program is a repo of one. See docs/relationships.md.

Sync is pull-only (fast-forward); converge (build/apply/restart) stays a separate,
explicit step.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from castle_core import git
from castle_core.relations import Repo, derive_repos

from castle_api import stream
from castle_api.config import get_config

repos_router = APIRouter(tags=["repos"])


def _resolve(key: str) -> tuple[Repo, object]:
    config = get_config()
    repos = derive_repos(config)
    if key not in repos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"repo '{key}' not found"
        )
    return repos[key], config


@repos_router.get("/repos")
def list_repos() -> list[dict]:
    """Every repo with members and last-known git state (no fetch — fast)."""
    out: list[dict] = []
    for repo in derive_repos(get_config()).values():
        st = git.git_status(Path(repo.path), fetch=False)
        out.append(
            {
                **dataclasses.asdict(repo),
                "branch": st.branch,
                "behind": st.behind,
                "dirty": st.dirty,
            }
        )
    return out


@repos_router.get("/repos/{key}/git")
def repo_git(key: str) -> dict:
    """A repo's git status (fetches, so ``behind`` is current) plus its members."""
    repo, _ = _resolve(key)
    return {
        **dataclasses.asdict(git.git_status(Path(repo.path), fetch=True)),
        "key": key,
        "programs": repo.programs,
        "deployments": repo.deployments,
    }


@repos_router.post("/repos/{key}/sync")
async def repo_sync(key: str) -> dict:
    """Fast-forward the repo's working copy. Pull-only — reports which deployments
    may now need a restart/apply, but does not converge them."""
    repo, _ = _resolve(key)
    before = git.head(Path(repo.path))
    ok, output = git.pull(Path(repo.path))
    if not ok:
        raise HTTPException(status_code=500, detail=output or "git pull failed")
    pulled = git.head(Path(repo.path)) != before
    if pulled:
        await stream.broadcast(
            "repo-sync", {"repo": key, "deployments": repo.deployments}
        )
    return {
        "repo": key,
        "status": "ok",
        "output": output,
        "pulled": pulled,
        "deployments": repo.deployments if pulled else [],
    }
