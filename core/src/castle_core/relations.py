"""The relationship model — derived, never stored. See docs/relationships.md.

Entities: **program**, **deployment**, **repo** (a repo is a git working copy;
programs sharing a toplevel form a monorepo). One encoded relation, **`requires`**
(a precondition, typed by ``kind``: ``system`` = must be installed, ``deployment``
= must exist). Everything else — repos, env wiring, fan-in, and the predicates
``functional?`` / ``fresh?`` / ``deployed?`` — is computed here on demand.

Governing rule: *predicates are derived; we encode only the non-derivable.* So this
module reads the encoded ``requires`` (plus ``system_dependencies`` as its
``kind: system`` alias) and derives the rest. It does **not** scrape env for
dependencies — env is generated *from* requirements, not the reverse.
"""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from castle_core import git
from castle_core.config import CastleConfig
from castle_core.manifest import Requirement


@dataclass
class Repo:
    key: str  # url-safe slug (basename of the working copy)
    path: str  # git toplevel
    url: str | None
    ref: str | None
    programs: list[str]
    deployments: list[str]
    behind: int | None = None  # commits behind upstream (None = unknown/no upstream)
    dirty: bool = False
    fresh: bool | None = None  # derived: at latest and clean (None = not evaluated)

    @property
    def multi(self) -> bool:
        """A monorepo — more than one program shares this working copy."""
        return len(self.programs) > 1


@dataclass
class Edge:
    src: str  # deployment name
    dst: str  # target: a package (system) or another deployment
    kind: str  # "system" | "deployment"
    bind: str | None = None  # env var to project the target URL into (deployment)


@dataclass
class Node:
    name: str  # deployment name
    program: str | None
    kind: str  # service|job|tool|static|reference
    repo: str | None
    depended_on_by: int  # distinct deployments that require this one (fan-in)
    unmet: list[str] = field(default_factory=list)  # unsatisfied requirements
    functional: bool = True  # derived: all requirements satisfied
    fresh: bool | None = None  # derived: its repo is at latest + clean
    deployed: bool | None = None  # derived: active in the registry (None = unknown)


@dataclass
class Model:
    repos: list[Repo] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


def _program_of(name: str, dep: object) -> str:
    return getattr(dep, "program", None) or name


def _slug(name: str, used: set[str]) -> str:
    base = name or "repo"
    key, n = base, 2
    while key in used:
        key, n = f"{base}-{n}", n + 1
    used.add(key)
    return key


def derive_repos(config: CastleConfig) -> dict[str, Repo]:
    """Group programs by the git working copy their source lives in."""
    by_top: dict[str, list[str]] = {}
    for pname, prog in config.programs.items():
        top = git.toplevel(prog.source) if prog.source else None
        if top:
            by_top.setdefault(top, []).append(pname)

    used: set[str] = set()
    repos: dict[str, Repo] = {}
    for top, progs in sorted(by_top.items()):
        progs = sorted(progs)
        url = next(
            (config.programs[p].repo for p in progs if config.programs[p].repo), None
        ) or git.remote_url(Path(top))
        ref = (
            next(
                (config.programs[p].ref for p in progs if config.programs[p].ref), None
            )
            or git.git_status(Path(top), fetch=False).branch
        )
        deps = sorted(
            d for d, dep in config.deployments.items() if _program_of(d, dep) in progs
        )
        repos[_slug(Path(top).name, used)] = Repo("", top, url, ref, progs, deps)
    for key, repo in repos.items():
        repo.key = key
    return repos


def requirements_of(config: CastleConfig, dep_name: str) -> list[Requirement]:
    """The full requirement set for a deployment: its own ``requires`` plus its
    program's ``requires`` and ``system_dependencies`` (the ``kind: system`` alias),
    de-duplicated by (kind, ref)."""
    dep = config.deployments[dep_name]
    prog = config.programs.get(_program_of(dep_name, dep))
    reqs: list[Requirement] = list(getattr(dep, "requires", []) or [])
    if prog:
        reqs += list(prog.requires)
        reqs += [
            Requirement(kind="system", ref=pkg) for pkg in prog.system_dependencies
        ]
    seen: set[tuple[str, str]] = set()
    out: list[Requirement] = []
    for r in reqs:
        if (r.kind, r.ref) not in seen:
            seen.add((r.kind, r.ref))
            out.append(r)
    return out


def _dpkg_installed(pkg: str) -> bool:
    """Whether a dpkg package is installed (the authoritative 'installed' check on
    Debian/Ubuntu). Returns False where dpkg isn't available."""
    dpkg = shutil.which("dpkg")
    if not dpkg:
        return False
    r = subprocess.run([dpkg, "-s", pkg], capture_output=True, text=True)
    return r.returncode == 0 and "install ok installed" in r.stdout


def _check(config: CastleConfig, req: Requirement) -> bool:
    """Is a single requirement satisfied? (The check is fixed by its kind.)"""
    if req.kind == "system":
        # `system_dependencies` holds PACKAGE names, not executables. A PATH lookup
        # only coincides with 'installed' when the package name equals its command
        # (pandoc, rsync) — for names like poppler-utils / texlive-latex-base /
        # docker-compose-plugin it never matches. Fast-path `which`, then ask the
        # package manager (the real meaning of 'installed').
        return shutil.which(req.ref) is not None or _dpkg_installed(req.ref)
    if req.kind == "deployment":
        return req.ref in config.deployments
    return True


def build_model(
    config: CastleConfig,
    check: bool = True,
    active: set[str] | None = None,
    freshness: bool = False,
) -> Model:
    """Compute the relationship model.

    - ``check`` (default): evaluate ``functional?`` (unmet requirements) via a live
      ``which`` / registry probe. ``check=False`` → pure structural model.
    - ``active``: names of currently-active deployments → the ``deployed?``
      predicate (left ``None`` when the caller has no runtime view).
    - ``freshness``: also evaluate ``fresh?`` per repo (a ``git status``, no fetch —
      last-known — so it stays a local, network-free probe over many repos)."""
    from castle_core.manifest import kind_for

    repos = derive_repos(config)
    if freshness:
        for repo in repos.values():
            st = git.git_status(Path(repo.path), fetch=False)
            repo.behind = st.behind
            repo.dirty = st.dirty
            repo.fresh = (st.behind == 0 or st.behind is None) and not st.dirty
    repo_of = {p: key for key, r in repos.items() for p in r.programs}
    fresh_of = {key: r.fresh for key, r in repos.items()}

    edges: list[Edge] = []
    for name in config.deployments:
        for r in requirements_of(config, name):
            edges.append(Edge(name, r.ref, r.kind, r.bind))

    fan_in = Counter(e.dst for e in edges if e.kind == "deployment")

    nodes: list[Node] = []
    for name, dep in config.deployments.items():
        unmet = (
            [
                f"{r.kind}:{r.ref}"
                for r in requirements_of(config, name)
                if not _check(config, r)
            ]
            if check
            else []
        )
        repo_key = repo_of.get(_program_of(name, dep))
        nodes.append(
            Node(
                name=name,
                program=_program_of(name, dep),
                kind=kind_for(dep),
                repo=repo_key,
                depended_on_by=fan_in.get(name, 0),
                unmet=unmet,
                functional=not unmet,
                fresh=fresh_of.get(repo_key) if (freshness and repo_key) else None,
                deployed=(name in active) if active is not None else None,
            )
        )
    return Model(repos=list(repos.values()), nodes=nodes, edges=edges)
