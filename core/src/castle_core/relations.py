"""The relationship model — derived, never stored. See docs/relationships.md.

Entities: **program**, **deployment**, **repo** (a repo is a git working copy;
programs sharing a toplevel form a monorepo). Preconditions come from two encoded
sources: a deployment's **`requires`** (other deployments it needs) and its
program's **`system_dependencies`** (host packages). These are unified here into one
requirement set (typed by ``kind``: ``deployment`` = must exist, ``system`` = must be
installed). Everything else — repos, env wiring, fan-in, and the predicates
``functional?`` / ``fresh?`` / ``deployed?`` — is computed here on demand.

Governing rule: *predicates are derived; we encode only the non-derivable.* So this
module reads the encoded ``requires`` + ``system_dependencies`` and derives the rest.
It does **not** scrape env for dependencies — env is generated *from* requirements,
not the reverse.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from castle_core import git
from castle_core.config import USER_TOOL_PATH_DIRS, CastleConfig
from castle_core.generators.systemd import runtime_path
from castle_core.manifest import Requirement, SystemdDeployment
from castle_core.stacks import ToolRequirement, tools_for


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
class Endpoint:
    """A socket a deployment exposes. ``protocol`` is a display heuristic — the
    manifest has no protocol field (expose is http XOR tcp), so raw TCP is refined
    by well-known port (else ``tcp``). A real protocol field is future work."""

    protocol: str  # "http" | "tcp" | "pg" | "bolt" | "mqtt" | "redis"
    port: int


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
    reach: str | None = None  # off|internal|public (systemd/caddy), else None
    endpoints: list[Endpoint] = field(default_factory=list)  # sockets it exposes
    base_url: str | None = None  # the target URL, for kind=="reference" (external)


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
            d for _k, d, dep in config.all_deployments() if _program_of(d, dep) in progs
        )
        repos[_slug(Path(top).name, used)] = Repo("", top, url, ref, progs, deps)
    for key, repo in repos.items():
        repo.key = key
    return repos


def requirements_of(config: CastleConfig, dep_name: str) -> list[Requirement]:
    """The full requirement set for a deployment: its own ``requires`` (deployment
    dependencies), its program's ``system_dependencies`` synthesized as
    ``kind: system`` requirements, and its stack's toolchains synthesized as
    ``kind: tool`` requirements — de-duplicated by (kind, ref)."""
    reqs: list[Requirement] = []
    # A bare name may span kinds — union their requirements (plus each program's
    # host-package deps as `kind: system` and its stack's toolchains as `kind: tool`).
    for _kind, dep in config.deployments_named(dep_name):
        reqs += list(getattr(dep, "requires", []) or [])
        prog = config.programs.get(_program_of(dep_name, dep))
        if prog:
            reqs += [
                Requirement(kind="system", ref=pkg) for pkg in prog.system_dependencies
            ]
            reqs += [
                Requirement(kind="tool", ref=t.command) for t in tools_for(prog.stack)
            ]
    seen: set[tuple[str, str]] = set()
    out: list[Requirement] = []
    for r in reqs:
        if (r.kind, r.ref) not in seen:
            seen.add((r.kind, r.ref))
            out.append(r)
    return out


def stack_tools_of(config: CastleConfig, dep_name: str) -> dict[str, ToolRequirement]:
    """command → its :class:`ToolRequirement`, for every stack toolchain the
    deployment(s) named ``dep_name`` need. The metadata (phase, install hint) behind
    the ``kind: tool`` requirements ``requirements_of`` synthesizes — used to check
    them (phase picks the PATH) and to hint a fix."""
    meta: dict[str, ToolRequirement] = {}
    for _kind, dep in config.deployments_named(dep_name):
        prog = config.programs.get(_program_of(dep_name, dep))
        if prog and prog.stack:
            for t in tools_for(prog.stack):
                meta.setdefault(t.command, t)
    return meta


def _dpkg_installed(pkg: str) -> bool:
    """Whether a dpkg package is installed (the authoritative 'installed' check on
    Debian/Ubuntu). Returns False where dpkg isn't available."""
    dpkg = shutil.which("dpkg")
    if not dpkg:
        return False
    r = subprocess.run([dpkg, "-s", pkg], capture_output=True, text=True)
    return r.returncode == 0 and "install ok installed" in r.stdout


def _build_path() -> str:
    """The PATH a *build/dev* verb runs with — the caller's own PATH plus the user
    tool dirs (mirrors ``stacks._build_env``, minus the per-program node pin resolved
    separately). Build-phase tools (pnpm, hugo, node) are checked against this."""
    dirs = [str(d) for d in USER_TOOL_PATH_DIRS if d.exists()]
    return ":".join([*dirs, os.environ.get("PATH", "")])


def _tool_available(dep: object, tool: ToolRequirement) -> bool:
    """Is a stack tool present *where the deployment needs it*? A ``run``/``both``
    tool of a systemd service must be on the **service's runtime PATH** (the curated
    unit PATH, which can differ from your shell — the drift this catches); every
    other case (build-only tools, or a non-service deployment like a static site) is
    checked against the build/dev PATH."""
    runs_service = isinstance(dep, SystemdDeployment)
    if tool.phase in ("run", "both") and runs_service:
        defaults = getattr(dep, "defaults", None)
        env_path = (defaults.env.get("PATH") if defaults else None) or None
        # `path_prepend` (resolved toolchain) lives on the registry deployment, not
        # the manifest one; absent here it's the base runtime PATH, which is what a
        # service without a pinned toolchain actually runs with.
        path = env_path or runtime_path(list(getattr(dep, "path_prepend", []) or ()))
        return shutil.which(tool.command, path=path) is not None
    return shutil.which(tool.command, path=_build_path()) is not None


def _check(
    config: CastleConfig,
    req: Requirement,
    dep: object | None = None,
    tool: ToolRequirement | None = None,
) -> bool:
    """Is a single requirement satisfied? The check is fixed by its ``kind``. For a
    ``tool`` requirement, ``dep`` and ``tool`` supply the deployment context and the
    stack-tool metadata (phase decides which PATH to probe)."""
    if req.kind == "system":
        # `system_dependencies` holds PACKAGE names, not executables. A PATH lookup
        # only coincides with 'installed' when the package name equals its command
        # (pandoc, rsync) — for names like poppler-utils / texlive-latex-base /
        # docker-compose-plugin it never matches. Fast-path `which`, then ask the
        # package manager (the real meaning of 'installed').
        return shutil.which(req.ref) is not None or _dpkg_installed(req.ref)
    if req.kind == "deployment":
        return bool(config.deployments_named(req.ref))
    if req.kind == "tool":
        # No metadata (unknown stack) → don't raise a false alarm.
        return tool is None or _tool_available(dep, tool)
    return True


def hint_for(req: Requirement, tool: ToolRequirement | None = None) -> str:
    """A copyable next step for an *unmet* requirement — the piece that makes a
    diagnostic actionable. ``tool`` carries a stack tool's precise install command."""
    if req.kind == "tool":
        return tool.install_hint if tool else f"install {req.ref}"
    if req.kind == "system":
        return f"sudo apt install {req.ref}"
    if req.kind == "deployment":
        return f"create & apply the '{req.ref}' deployment"
    return ""


# Well-known TCP ports → a friendlier protocol label (display heuristic only).
_TCP_PROTOCOL = {5432: "pg", 7687: "bolt", 1883: "mqtt", 6379: "redis"}


def _endpoints_of(dep: object) -> list[Endpoint]:
    """The sockets a deployment exposes, derived from its manifest — reusing the
    ``http_exposed`` / ``tcp_port`` accessors (SystemdDeployment only). Tools,
    statics, and references have no expose block and yield ``[]``."""
    eps: list[Endpoint] = []
    if not isinstance(dep, SystemdDeployment):
        return eps  # only systemd services/jobs carry an expose block
    exp = dep.expose
    if dep.http_exposed and exp and exp.http:
        eps.append(Endpoint("http", exp.http.internal.port))
    if dep.tcp_port is not None:
        eps.append(Endpoint(_TCP_PROTOCOL.get(dep.tcp_port, "tcp"), dep.tcp_port))
    return eps


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
    for _k, name, _d in config.all_deployments():
        for r in requirements_of(config, name):
            edges.append(Edge(name, r.ref, r.kind, r.bind))

    fan_in = Counter(e.dst for e in edges if e.kind == "deployment")

    nodes: list[Node] = []
    for _nk, name, dep in config.all_deployments():
        tmeta = stack_tools_of(config, name) if check else {}
        unmet = (
            [
                f"{r.kind}:{r.ref}"
                for r in requirements_of(config, name)
                if not _check(config, r, dep=dep, tool=tmeta.get(r.ref))
            ]
            if check
            else []
        )
        prog_name = _program_of(name, dep)
        repo_key = repo_of.get(prog_name)
        nodes.append(
            Node(
                name=name,
                program=prog_name,
                kind=_nk,
                repo=repo_key,
                depended_on_by=fan_in.get(name, 0),
                unmet=unmet,
                functional=not unmet,
                fresh=fresh_of.get(repo_key) if (freshness and repo_key) else None,
                deployed=(name in active) if active is not None else None,
                reach=getattr(getattr(dep, "reach", None), "value", None),
                endpoints=_endpoints_of(dep),
                base_url=getattr(dep, "base_url", None),
            )
        )
    return Model(repos=list(repos.values()), nodes=nodes, edges=edges)
