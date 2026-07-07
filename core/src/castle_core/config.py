"""Castle configuration and registry management."""

from __future__ import annotations

import os
import re
from dataclasses import InitVar, dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, TypeAdapter

from castle_core.manifest import (
    AgentSpec,
    DeploymentSpec,
    ProgramSpec,
    kind_for,
)

# Validator for the manager-discriminated deployment union (it's an Annotated
# Union, not a BaseModel, so it needs a TypeAdapter to parse a dict).
_DEPLOYMENT_ADAPTER: TypeAdapter[DeploymentSpec] = TypeAdapter(DeploymentSpec)


def _resolve_castle_home() -> Path:
    """Resolve the castle home directory (config, code, artifacts, secrets).

    Defaults to ~/.castle. Override with the CASTLE_HOME environment variable
    (supports ~ and relative paths, which are expanded and made absolute).
    """
    override = os.environ.get("CASTLE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".castle"


_DEFAULT_DATA_DIR = Path("/data/castle")
_DEFAULT_REPOS_DIR = Path("/data/repos")


class CastleDirError(RuntimeError):
    """A required castle directory can't be created (e.g. data_dir outside a writable
    parent). Carries an actionable message; surfaced to the CLI and the api instead of
    a bare PermissionError traceback."""


def _resolve_root_path(
    env_var: str, yaml_value: object, anchor: Path, default: Path
) -> Path:
    """Resolve a configurable root with precedence: env var > castle.yaml > default.

    `~` is expanded; a relative path is anchored to `anchor` (the dir containing
    castle.yaml) — never cwd, so the CLI (shell cwd) and the api service (unit cwd)
    resolve identically. The built-in default is returned as-is (so it compares equal
    for the "persist only when non-default" check in save_config)."""
    raw = os.environ.get(env_var) or yaml_value
    if not raw:
        return default
    p = Path(str(raw)).expanduser()
    if not p.is_absolute():
        p = anchor / p
    return p.resolve()


CASTLE_HOME = _resolve_castle_home()
CODE_DIR = CASTLE_HOME / "code"
ARTIFACTS_DIR = CASTLE_HOME / "artifacts"
SPECS_DIR = ARTIFACTS_DIR / "specs"
CONTENT_DIR = ARTIFACTS_DIR / "content"
SECRETS_DIR = CASTLE_HOME / "secrets"
# data_dir and repos_dir are deliberately NOT module constants. Unlike the CASTLE_HOME
# family above (env-or-default — the dir that *holds* castle.yaml can't be configured
# inside it), these are per-instance settings read from castle.yaml. A module global
# would be a second copy of that value, resolved once at import against one process's
# environment — exactly what let the CLI and the api service drift. They live only on
# the loaded CastleConfig; read config.data_dir / config.repos_dir (see load_config).

# User tool directories — the single source of truth for "where our CLIs live".
# Used both at build time (dev-verb subprocess PATH) and at run time (generated
# systemd unit PATH) so a service sees the same tools castle used to build it.
# Order matters: pnpm's modern standalone installer puts its shim in
# $PNPM_HOME/bin, which must win over the bare dir (older installs leave a stale
# version wrapper there). nvm/node is intentionally omitted — it's versioned and
# brittle to hardcode. A program's node is resolved per-program from its declared
# pin (.node-version/.nvmrc/engines) and prepended ahead of these dirs at both the
# build subprocess (stacks._build_env) and the runtime unit PATH (Deployment
# .path_prepend) — see castle_core.toolchains.
USER_TOOL_PATH_DIRS = [
    Path.home() / ".local" / "bin",
    Path.home() / ".local" / "share" / "pnpm" / "bin",
    Path.home() / ".local" / "share" / "pnpm",
    Path("/usr/local/go/bin"),
]

# Backwards-compat aliases (used by existing imports)
GENERATED_DIR = SPECS_DIR
STATIC_DIR = CONTENT_DIR


def find_castle_root() -> Path:
    """Find the castle config root (directory containing castle.yaml).

    Search order:
    1. ~/.castle/castle.yaml (the canonical instance location)
    2. Walk up from cwd (for development/testing)
    """
    # Canonical location first
    if (CASTLE_HOME / "castle.yaml").exists():
        return CASTLE_HOME
    # Fallback: walk up from cwd
    current = Path.cwd()
    while current != current.parent:
        if (current / "castle.yaml").exists():
            return current
        current = current.parent
    raise FileNotFoundError(
        f"Could not find castle.yaml.\nExpected at: {CASTLE_HOME / 'castle.yaml'}"
    )


@dataclass
class GatewayConfig:
    """Gateway configuration."""

    port: int = 9000
    # None/"off" → HTTP-only gateway. "acme" → real Let's Encrypt wildcard cert
    # (*.domain) via a DNS-01 challenge; publicly trusted, no CA to install.
    tls: str | None = None
    # acme mode only: the zone for the wildcard cert and host-route subdomains
    # (e.g. "civil.payne.io" → host routes become <service>.civil.payne.io).
    domain: str | None = None
    acme_email: str | None = None
    acme_dns_provider: str = "cloudflare"
    # Public exposure via the Cloudflare tunnel (optional). `public_domain` is the
    # separate zone public services are published at (e.g. "pub.payne.io" →
    # <service>.pub.payne.io), kept distinct from `domain` so internal subdomain
    # names never appear in public DNS. `tunnel_id` is the cloudflared tunnel UUID.
    public_domain: str | None = None
    tunnel_id: str | None = None
    # acme mode only: emit the `events { on cert_obtained exec castle tls reconcile }`
    # hook so certs materialized onto raw-TCP services refresh on renewal. Requires
    # the events-exec plugin in the gateway's Caddy build — set true only once that
    # Caddy is installed (see docs/tcp-exposure.md §5). Default false keeps a
    # plugin-less gateway parseable.
    cert_hook: bool = False


# Deployment kinds and the CastleConfig store each lives in. Kind is STRUCTURAL —
# a deployment's identity is (name, kind), so names are unique within a kind but may
# collide across kinds (a `backup` tool + service + job coexist). `kind_for` (manifest)
# stays only to validate that a spec's manager/schedule matches the store it's in.
KINDS = ("service", "job", "tool", "static", "reference")
_KIND_STORE = {
    "service": "services",
    "job": "jobs",
    "tool": "tools",
    "static": "statics",
    "reference": "references",
}


@dataclass
class CastleConfig:
    """Full castle configuration."""

    root: Path
    gateway: GatewayConfig
    repo: Path | None
    programs: dict[str, ProgramSpec]
    # Per-kind deployment stores (the primary representation). Each is name-keyed and
    # unique within its kind; a name may appear in more than one store. There is no
    # single flat `deployments` dict — use `all_deployments()` / `deployments_named()`
    # / the kind store directly (`config.services[name]`).
    services: dict[str, DeploymentSpec] = field(default_factory=dict)
    jobs: dict[str, DeploymentSpec] = field(default_factory=dict)
    tools: dict[str, DeploymentSpec] = field(default_factory=dict)
    statics: dict[str, DeploymentSpec] = field(default_factory=dict)
    references: dict[str, DeploymentSpec] = field(default_factory=dict)
    # Launchable agent CLIs for the dashboard terminal UX (assistant-agnostic).
    # Optional; empty means the API falls back to a built-in default set.
    agents: dict[str, AgentSpec] = field(default_factory=dict)
    # Configurable roots — the single source of truth (no module-constant twin).
    # load_config sets them (env > castle.yaml > default); a bare constructor gets the
    # built-in defaults so tests/callers that don't care stay valid.
    data_dir: Path = field(default_factory=lambda: _DEFAULT_DATA_DIR)
    repos_dir: Path = field(default_factory=lambda: _DEFAULT_REPOS_DIR)
    # Fleet role: "authority" (may write shared config/secrets to the mesh) or
    # "follower" (reconciles from it). Static — pinned here, no election.
    role: str = "follower"
    # Construction convenience only (not stored): a flat name→spec dict is routed
    # into the per-kind stores by kind_for. Lets callers/tests hand us a flat map
    # without pre-splitting it; there is still no flat `deployments` attribute.
    deployments: InitVar[dict[str, DeploymentSpec] | None] = None

    def __post_init__(self, deployments: dict[str, DeploymentSpec] | None) -> None:
        for name, spec in (deployments or {}).items():
            self.store_for(kind_for(spec))[name] = spec

    def store_for(self, kind: str) -> dict[str, DeploymentSpec]:
        """The name-keyed deployment store for a kind (service|job|tool|static|reference)."""
        return getattr(self, _KIND_STORE[kind])

    def all_deployments(self) -> list[tuple[str, str, DeploymentSpec]]:
        """Every deployment as `(kind, name, spec)`, kind-then-name ordered. The single
        shared iterate-all — the converge loop dispatches on `spec.manager`, so the
        machinery stays shared; only the namespace is split by kind."""
        out: list[tuple[str, str, DeploymentSpec]] = []
        for kind in KINDS:
            store = self.store_for(kind)
            out.extend((kind, name, store[name]) for name in sorted(store))
        return out

    def deployment(self, kind: str, name: str) -> DeploymentSpec | None:
        """A single deployment by its `(kind, name)` identity, or None."""
        return self.store_for(kind).get(name)

    def deployments_named(self, name: str) -> list[tuple[str, DeploymentSpec]]:
        """`(kind, spec)` for every kind that has a deployment with this bare name
        (≤5). Used where a caller has only a name and no kind (apply/restart/redirect)."""
        return [(kind, spec) for kind, n, spec in self.all_deployments() if n == name]

    def deployments_of(self, program: str) -> list[tuple[str, str]]:
        """A program's deployments as (deployment-name, kind) pairs, name-sorted.

        A deployment belongs to a program when it names it (`program:`) or shares its
        name (the 1:1 tool/static case). Empty for a bare, undeployed program.
        """
        return sorted(
            (name, kind)
            for kind, name, dep in self.all_deployments()
            if name == program or dep.program == program
        )

    @property
    def frontends(self) -> dict[str, ProgramSpec]:
        """Return programs that are frontends (have build outputs)."""
        return {
            k: v
            for k, v in self.programs.items()
            if v.build and (v.build.outputs or v.build.commands)
        }


def resolve_env_split(
    env: dict[str, str], context: dict[str, str] | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve placeholders, splitting secret-bearing vars from plain ones.

    Returns ``(plain, secret)``. A var is *secret-bearing* if its raw value
    contained a ``${secret:...}`` reference — including composite values like
    ``neo4j/${secret:NEO4J_PASSWORD}``. Both dicts hold fully-resolved values;
    partitioning lets callers keep secrets out of unit files and process argv
    (routing them through a mode-0600 env file) while inlining the rest.

    - ``${secret:NAME}`` resolves via the active secret backend (file or OpenBao).
    - ``${port}`` / ``${data_dir}`` / ``${name}`` / ``${public_url}`` (and
      anything else in ``context``) expand to castle's computed values, so a
      service maps them to whatever env var its program reads (e.g.
      ``MY_PORT: ${port}``) without hardcoding or castle silently injecting a
      guessed var name. ``${public_url}`` is the service's gateway-facing base
      URL (``https://<name>.<domain>`` under acme) — the origin an app allowlists.
    """
    context = context or {}
    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    for key, value in env.items():

        def replace_var(match: re.Match[str]) -> str:
            ref = match.group(1)
            if ref.startswith("secret:"):
                return _read_secret(ref[7:])
            if ref in context:
                return context[ref]
            return match.group(0)

        resolved = re.sub(r"\$\{([^}]+)\}", replace_var, value)
        if re.search(r"\$\{secret:[^}]+\}", value):
            secret[key] = resolved
        else:
            plain[key] = resolved
    return plain, secret


def resolve_placeholders(value: str, context: dict[str, str] | None) -> str:
    """Expand ``${key}`` refs in a single string from ``context``.

    The one ``${...}`` grammar shared by env resolution (:func:`resolve_env_split`)
    and run-spec expansion (argv/volumes/env in a container launch), so a new
    placeholder only has to be added to the context dict, never to a second engine.
    Unknown refs — including ``${secret:...}`` — pass through untouched (secrets
    never belong in argv; they go via ``--env-file``). Write ``$${key}`` to emit a
    literal ``${key}`` (e.g. a container arg the container's own shell must expand).
    """
    if not context:
        return value

    def replace_var(match: re.Match[str]) -> str:
        ref = match.group(1)
        return context.get(ref, match.group(0))

    # Split on the `$$` escape so an escaped `$${x}` never reaches the substitution
    # regex, then rejoin with a literal `$`.
    return "$".join(
        re.sub(r"\$\{([^}]+)\}", replace_var, part) for part in value.split("$$")
    )


def resolve_env_vars(
    env: dict[str, str], context: dict[str, str] | None = None
) -> dict[str, str]:
    """Resolve placeholders in env values (secrets included), preserving order.

    Convenience wrapper over :func:`resolve_env_split` for callers that want a
    single flat dict. Prefer ``resolve_env_split`` when secrets must be kept out
    of generated artifacts.
    """
    plain, secret = resolve_env_split(env, context)
    return {k: secret[k] if k in secret else plain[k] for k in env}


def _secrets_settings() -> dict:
    """The ``secrets:`` block of castle.yaml — selects the backend."""
    try:
        data = yaml.safe_load((CASTLE_HOME / "castle.yaml").read_text()) or {}
        return data.get("secrets") or {}
    except Exception:
        return {}


def read_secret(name: str) -> str | None:
    """Resolve a secret via the active backend, or None if unset.

    The public helper for code that reads secrets directly (DNS/supabase/etc.) so
    everything goes through the one backend rather than the filesystem.
    """
    from castle_core.secret_backends import build_backend

    return build_backend(SECRETS_DIR, _secrets_settings()).read(name)


def _read_secret(name: str) -> str:
    """Like :func:`read_secret` but returns a ``<MISSING_SECRET:...>`` placeholder
    for unresolved secrets (used by ``${secret:...}`` env substitution)."""
    value = read_secret(name)
    return value if value is not None else f"<MISSING_SECRET:{name}>"


def _parse_program(name: str, data: dict) -> ProgramSpec:
    """Parse a programs: entry into a ProgramSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return ProgramSpec.model_validate(data_copy)


def _normalize_deployment_dict(data: dict) -> dict:
    """Map a legacy service/job entry to the manager-discriminated shape.

    Legacy entries carry `run.runner` (including static/path/remote); new entries
    carry `manager` and (for systemd) `run.launcher`. New-shape entries pass through.
    """
    if "manager" in data:
        return data
    d = dict(data)
    run = dict(d.pop("run", None) or {})
    runner = run.get("runner")
    if runner == "static":
        d["manager"] = "caddy"
        if run.get("root"):
            d["root"] = run["root"]
    elif runner == "path":
        d["manager"] = "path"
    elif runner == "remote":
        d["manager"] = "none"
        if run.get("base_url"):
            d["base_url"] = run["base_url"]
        if run.get("health_url"):
            d["health_url"] = run["health_url"]
    else:
        # A process launcher (python/command/container/compose/node) → systemd.
        d["manager"] = "systemd"
        launch = {k: v for k, v in run.items() if k != "runner"}
        launch["launcher"] = runner
        d["run"] = launch
    return d


def _parse_deployment(name: str, data: dict) -> DeploymentSpec:
    """Parse a deployment entry (new or legacy shape) into a DeploymentSpec."""
    data_copy = _normalize_deployment_dict(data)
    data_copy = dict(data_copy)
    data_copy["id"] = name
    return _DEPLOYMENT_ADAPTER.validate_python(data_copy)


def _load_resource_dir(directory: Path) -> dict[str, dict]:
    """Load every *.yaml file in a resource directory.

    The filename stem becomes the resource id. Returns a mapping of
    id → parsed YAML dict (empty mappings normalized to {}).
    """
    result: dict[str, dict] = {}
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.yaml")):
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        result[path.stem] = data
    return result


def parse_gateway(gateway_data: dict) -> GatewayConfig:
    """Build a GatewayConfig from a castle.yaml ``gateway:`` mapping.

    The single parser shared by ``load_config`` and the API's whole-file editor,
    so a newly added gateway field can't be honored in one place and silently
    dropped in the other (which is exactly how ``cert_hook`` got wiped on a
    full-config save).
    """
    return GatewayConfig(
        port=gateway_data.get("port", 9000),
        tls=gateway_data.get("tls"),
        domain=gateway_data.get("domain"),
        acme_email=gateway_data.get("acme_email"),
        acme_dns_provider=gateway_data.get("acme_dns_provider", "cloudflare"),
        public_domain=gateway_data.get("public_domain"),
        tunnel_id=gateway_data.get("tunnel_id"),
        cert_hook=gateway_data.get("cert_hook", False),
    )


def load_config(root: Path | None = None) -> CastleConfig:
    """Load castle config: global castle.yaml + programs/ and deployments/ dirs."""
    if root is None:
        root = find_castle_root()

    config_path = root / "castle.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Castle config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    gateway = parse_gateway(data.get("gateway", {}))

    # repo: field points to the git repo for repo-relative sources
    repo_path: Path | None = None
    if data.get("repo"):
        repo_path = Path(data["repo"]).expanduser()

    # Configurable roots: env > this file's data_dir/repos_dir > default, anchored to
    # `root` (the dir holding this castle.yaml) so a per-call load_config is correct
    # regardless of the import-time constants (which resolved against CASTLE_HOME).
    data_dir = _resolve_root_path(
        "CASTLE_DATA_DIR", data.get("data_dir"), root, _DEFAULT_DATA_DIR
    )
    repos_dir = _resolve_root_path(
        "CASTLE_REPOS_DIR", data.get("repos_dir"), root, _DEFAULT_REPOS_DIR
    )

    programs: dict[str, ProgramSpec] = {}
    for name, comp_data in _load_resource_dir(root / "programs").items():
        prog = _parse_program(name, comp_data)
        # Resolve source paths to absolute
        if prog.source:
            if prog.source.startswith("repo:") and repo_path:
                # repo:castle-api → /data/repos/castle/castle-api
                prog.source = str(repo_path / prog.source[5:])
            elif not Path(prog.source).is_absolute():
                prog.source = str(root / prog.source)
        programs[name] = prog

    stores = _load_deployments(root)
    _validate_subdomains(stores)

    agents: dict[str, AgentSpec] = {
        name: AgentSpec.model_validate(spec or {})
        for name, spec in (data.get("agents") or {}).items()
    }

    config = CastleConfig(
        root=root,
        repo=repo_path,
        gateway=gateway,
        programs=programs,
        agents=agents,
        data_dir=data_dir,
        repos_dir=repos_dir,
        role=data.get("role", "follower"),
        **stores,
    )
    return config


def _validate_subdomains(stores: dict[str, dict[str, DeploymentSpec]]) -> None:
    """A gateway subdomain (``<name>.<domain>``) must be globally unique across kinds.
    Only HTTP-exposed kinds claim one: a proxied service, or a static site. A name may
    still be a tool/service/job trio (only the service is HTTP-exposed), but a service
    and a static can't share a name (they'd fight over the same subdomain)."""
    claimants: dict[str, list[str]] = {}
    for name, spec in stores["services"].items():
        if getattr(spec, "http_exposed", False):
            claimants.setdefault(name, []).append("service")
    for name in stores["statics"]:
        claimants.setdefault(name, []).append("static")
    for name, kinds in claimants.items():
        if len(kinds) > 1:
            raise ValueError(
                f"subdomain '{name}' is claimed by multiple HTTP-exposed deployments "
                f"({', '.join(kinds)}); a name can be HTTP-exposed by at most one kind"
            )


def _load_deployments(root: Path) -> dict[str, dict[str, DeploymentSpec]]:
    """Load the per-kind deployment stores for a config root.

    New layout: ``deployments/<store>/<name>.yaml`` (store = services|jobs|tools|
    statics|references). Read-compat for the pre-migration layouts: flat
    ``deployments/*.yaml`` files, and the older ``services/``+``jobs/`` split. Every
    file is routed to its store by ``kind_for(spec)`` — the dir is a namespace, the
    spec's manager/schedule is the source of truth (they must agree post-migration).
    """
    stores: dict[str, dict[str, DeploymentSpec]] = {s: {} for s in _KIND_STORE.values()}

    def route(name: str, data: dict) -> None:
        spec = _parse_deployment(name, data)
        stores[_KIND_STORE[kind_for(spec)]][name] = spec

    dep_dir = root / "deployments"
    # New per-kind subdirs.
    for store in _KIND_STORE.values():
        for name, data in _load_resource_dir(dep_dir / store).items():
            route(name, data)
    # Legacy flat deployments/*.yaml (top-level only — subdirs handled above).
    for name, data in _load_resource_dir(dep_dir).items():
        route(name, data)
    # Oldest layout: services/ + jobs/ dirs, only if there's no deployments/ dir.
    if not dep_dir.is_dir():
        for legacy in ("services", "jobs"):
            for name, data in _load_resource_dir(root / legacy).items():
                route(name, data)
    return stores


def _clean_for_yaml(data: object, preserve_keys: set[str] | None = None) -> object:
    """Recursively remove empty lists and non-structural empty dicts."""
    if preserve_keys is None:
        preserve_keys = _STRUCTURAL_KEYS
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            v = _clean_for_yaml(v, preserve_keys)
            # Keep structural keys even if empty dict
            if k in preserve_keys and isinstance(v, dict):
                cleaned[k] = v
                continue
            # Skip empty collections
            if isinstance(v, (list, dict)) and not v:
                continue
            cleaned[k] = v
        return cleaned
    elif isinstance(data, list):
        return [_clean_for_yaml(item, preserve_keys) for item in data]
    return data


# Keys whose presence is structurally significant even with all-default values.
# We serialize these as empty dicts `{}` so they survive a roundtrip.
_STRUCTURAL_KEYS = {
    "manage",
    "systemd",
    "expose",
}


def _spec_to_yaml_dict(spec: BaseModel) -> dict:
    """Serialize a ProgramSpec or DeploymentSpec to a YAML-friendly dict."""
    exclude_fields = {"id"}
    full = spec.model_dump(mode="json", exclude_none=True, exclude=exclude_fields)
    minimal = spec.model_dump(
        mode="json", exclude_none=True, exclude=exclude_fields, exclude_defaults=True
    )

    def merge(full_val: object, min_val: object | None, key: str = "") -> object:
        if isinstance(full_val, dict):
            result = {}
            for k, fv in full_val.items():
                mv = min_val.get(k) if isinstance(min_val, dict) else None
                if k in _STRUCTURAL_KEYS:
                    merged = merge(fv, mv, k)
                    if merged is not None:
                        result[k] = merged
                elif mv is not None:
                    result[k] = merge(fv, mv, k)
                elif isinstance(fv, dict):
                    merged = merge(fv, None, k)
                    if merged:
                        result[k] = merged
            return result if result else ({} if key in _STRUCTURAL_KEYS else result)
        elif isinstance(full_val, list):
            if min_val is not None:
                return full_val
            return []
        else:
            if min_val is not None:
                return full_val
            return None

    result = merge(full, minimal)
    cleaned = _clean_for_yaml(result)
    return cleaned if isinstance(cleaned, dict) else {}


def _program_to_yaml_dict(spec: ProgramSpec, config: CastleConfig) -> dict:
    """Serialize a ProgramSpec, rewriting absolute source paths to relative."""
    d = _spec_to_yaml_dict(spec)
    if d.get("source") and Path(d["source"]).is_absolute():
        src = Path(d["source"])
        # If source is under repo, store as repo:relative
        if config.repo:
            try:
                d["source"] = "repo:" + str(src.relative_to(config.repo))
                return d
            except ValueError:
                pass
        # Otherwise store relative to config root
        try:
            d["source"] = str(src.relative_to(config.root))
        except ValueError:
            pass  # not under root — keep absolute
    return d


def _write_resource_dir(directory: Path, specs: dict[str, dict]) -> None:
    """Write each spec to <directory>/<name>.yaml and prune orphaned files."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, d in specs.items():
        with open(directory / f"{name}.yaml", "w") as f:
            yaml.dump(d, f, default_flow_style=False, sort_keys=False)
    # Prune files with no corresponding in-memory entry
    for path in directory.glob("*.yaml"):
        if path.stem not in specs:
            path.unlink()


def save_config(config: CastleConfig) -> None:
    """Save castle config: global castle.yaml + programs/ and deployments/ dirs."""
    gateway_data: dict = {"port": config.gateway.port}
    if config.gateway.tls:
        gateway_data["tls"] = config.gateway.tls
    if config.gateway.domain:
        gateway_data["domain"] = config.gateway.domain
    if config.gateway.acme_email:
        gateway_data["acme_email"] = config.gateway.acme_email
    # Only persist the provider when non-default, to keep castle.yaml minimal.
    if (
        config.gateway.acme_dns_provider
        and config.gateway.acme_dns_provider != "cloudflare"
    ):
        gateway_data["acme_dns_provider"] = config.gateway.acme_dns_provider
    if config.gateway.public_domain:
        gateway_data["public_domain"] = config.gateway.public_domain
    if config.gateway.tunnel_id:
        gateway_data["tunnel_id"] = config.gateway.tunnel_id
    if config.gateway.cert_hook:
        gateway_data["cert_hook"] = config.gateway.cert_hook
    data: dict = {"gateway": gateway_data}
    if config.repo:
        data["repo"] = str(config.repo)
    # Persist the configurable roots only when non-default, keeping castle.yaml minimal.
    # These MUST round-trip: save_config rewrites the file from scratch, so a root that
    # isn't re-emitted here would be silently dropped on the next apply.
    if config.data_dir != _DEFAULT_DATA_DIR:
        data["data_dir"] = str(config.data_dir)
    if config.repos_dir != _DEFAULT_REPOS_DIR:
        data["repos_dir"] = str(config.repos_dir)
    if config.agents:
        data["agents"] = {
            n: s.model_dump(exclude_none=True, exclude_defaults=True)
            for n, s in config.agents.items()
        }

    config_path = config.root / "castle.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    _write_resource_dir(
        config.root / "programs",
        {n: _program_to_yaml_dict(s, config) for n, s in config.programs.items()},
    )
    # Per-kind: deployments/<store>/<name>.yaml (each store pruned independently).
    dep_dir = config.root / "deployments"
    for kind, store in _KIND_STORE.items():
        _write_resource_dir(
            dep_dir / store,
            {n: _spec_to_yaml_dict(d) for n, d in config.store_for(kind).items()},
        )
    # Migration cleanup: drop any pre-migration flat deployments/*.yaml files.
    if dep_dir.is_dir():
        for path in dep_dir.glob("*.yaml"):
            path.unlink()


def ensure_dirs(config: CastleConfig) -> None:
    """Ensure castle directories exist. Takes the config so the data dir comes from the
    one source of truth (config.data_dir), not a process-resolved global."""
    CASTLE_HOME.mkdir(parents=True, exist_ok=True)
    CODE_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    # The data dir can live outside $HOME (a dedicated volume), so its parent may be
    # unwritable or absent — fail loud with a fix, not a bare PermissionError.
    data_dir = config.data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise CastleDirError(
            f"Cannot create data dir {data_dir}: {e.strerror or e}. "
            f"Set data_dir: in {CASTLE_HOME / 'castle.yaml'} (or export CASTLE_DATA_DIR) "
            f"to a writable path, or create it: "
            f"sudo mkdir -p {data_dir} && sudo chown $(id -un) {data_dir}"
        ) from e
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    # Generated per-deployment secret env files (EnvironmentFile= / --env-file)
    # live here, kept out of unit files and process argv.
    secret_env_dir = SECRETS_DIR / "env"
    secret_env_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_env_dir, 0o700)
