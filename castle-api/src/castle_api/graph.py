"""The relationship model as JSON — repos, `requires` edges, derived status.

Read-only diagnostic (see docs/relationships.md). Everything is computed on the
fly: repos from git, predicates (functional/fresh) from config + git. Nothing
stored.
"""

from __future__ import annotations

import dataclasses

from fastapi import APIRouter

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
