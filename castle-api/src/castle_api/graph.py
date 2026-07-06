"""The relationship model as JSON — repos, `requires` edges, derived status.

Read-only diagnostic (see docs/relationships.md). Everything is computed on the
fly: repos from git, predicates (functional/fresh) from config + git. Nothing
stored.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter

from castle_core.audit import suggest_consumption
from castle_core.relations import build_model

from castle_api.config import get_config

graph_router = APIRouter(tags=["graph"])


@graph_router.get("/graph")
def get_graph() -> dict:
    """The whole relationship model: repos (with freshness), deployment nodes (with
    `functional?`), and `requires` edges."""
    model = build_model(get_config(), check=True, freshness=True)
    return {
        "repos": [dataclasses.asdict(r) for r in model.repos],
        "nodes": [dataclasses.asdict(n) for n in model.nodes],
        "edges": [dataclasses.asdict(e) for e in model.edges],
    }


@graph_router.get("/graph/suggestions")
def get_suggestions() -> dict:
    """Undeclared-consumption *suggestions* — an opt-in advisory that matches each
    deployment's env endpoint values against provider sockets. Never writes; the
    graph itself stays declaration-derived. Accept one by declaring the `requires`."""
    return {"suggestions": [dataclasses.asdict(s) for s in suggest_consumption(get_config())]}
