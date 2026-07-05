"""castle graph — the relationship model: repos, `requires` edges, derived status.

A read-only diagnostic (see docs/relationships.md). Nothing here is stored — repos
come from git, predicates (functional/fresh/deployed) are computed on the fly.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from castle_cli.config import load_config

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"


def run_graph(args: argparse.Namespace) -> int:
    from castle_core.relations import build_model

    config = load_config()
    model = build_model(config, check=True, freshness=True)

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "repos": [dataclasses.asdict(r) for r in model.repos],
                    "nodes": [dataclasses.asdict(n) for n in model.nodes],
                    "edges": [dataclasses.asdict(e) for e in model.edges],
                },
                indent=2,
            )
        )
        return 0

    monos = [r for r in model.repos if r.multi]
    print(f"{BOLD}Repos{RESET} ({len(model.repos)}, {len(monos)} monorepo)")
    for r in monos:
        fresh = (
            ""
            if r.fresh is None
            else (f" {GREEN}fresh{RESET}" if r.fresh else f" {YELLOW}stale{RESET}")
        )
        print(f"  {CYAN}{r.key}{RESET}{fresh} {DIM}→ {', '.join(r.programs)}{RESET}")

    edges = [e for e in model.edges if e.kind == "deployment"]
    print(f"\n{BOLD}requires{RESET} (deployment → deployment): {len(edges)}")
    for e in edges:
        bind = f" {DIM}→ ${e.bind}{RESET}" if e.bind else ""
        print(f"  {e.src} {DIM}requires{RESET} {e.dst}{bind}")
    if not edges:
        print(f"  {DIM}(none declared — front-end/back-end deps have no encoded edge yet){RESET}")

    unhealthy = [n for n in model.nodes if not n.functional]
    print(f"\n{BOLD}functional?{RESET} — {len(unhealthy)} with unmet requirements")
    for n in unhealthy:
        print(f"  {RED}✗{RESET} {n.name} {DIM}unmet: {', '.join(n.unmet)}{RESET}")
    if not unhealthy:
        print(f"  {GREEN}✓ all functional{RESET}")

    depended = sorted((n for n in model.nodes if n.depended_on_by), key=lambda n: -n.depended_on_by)
    if depended:
        print(f"\n{BOLD}widely depended-on{RESET}")
        for n in depended:
            print(f"  {n.name} {DIM}← {n.depended_on_by} dependent(s){RESET}")
    return 0
