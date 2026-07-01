"""Castle configuration and registry management."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from castle_core.manifest import (
    JobSpec,
    ProgramSpec,
    ServiceSpec,
)


def _resolve_castle_home() -> Path:
    """Resolve the castle home directory (config, code, artifacts, secrets).

    Defaults to ~/.castle. Override with the CASTLE_HOME environment variable
    (supports ~ and relative paths, which are expanded and made absolute).
    """
    override = os.environ.get("CASTLE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".castle"


def _resolve_data_dir() -> Path:
    """Resolve the program data directory (service/program data I/O).

    Decoupled from CASTLE_HOME so bulk data can live on a dedicated volume.
    Defaults to /data/castle. Override with the CASTLE_DATA_DIR environment
    variable (supports ~ and relative paths, which are expanded and made absolute).
    """
    override = os.environ.get("CASTLE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path("/data/castle")


def _resolve_repos_dir() -> Path:
    """Resolve where program source repos live by default.

    `castle create` scaffolds and `castle add` adopts repos under here. Programs
    may also live anywhere (source: is an absolute path); this is just the default
    home for new ones. Override with CASTLE_REPOS_DIR. Defaults to /data/repos.
    """
    override = os.environ.get("CASTLE_REPOS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path("/data/repos")


CASTLE_HOME = _resolve_castle_home()
CODE_DIR = CASTLE_HOME / "code"
ARTIFACTS_DIR = CASTLE_HOME / "artifacts"
SPECS_DIR = ARTIFACTS_DIR / "specs"
CONTENT_DIR = ARTIFACTS_DIR / "content"
DATA_DIR = _resolve_data_dir()
SECRETS_DIR = CASTLE_HOME / "secrets"
REPOS_DIR = _resolve_repos_dir()

# User tool directories — the single source of truth for "where our CLIs live".
# Used both at build time (dev-verb subprocess PATH) and at run time (generated
# systemd unit PATH) so a service sees the same tools castle used to build it.
# Order matters: pnpm's modern standalone installer puts its shim in
# $PNPM_HOME/bin, which must win over the bare dir (older installs leave a stale
# version wrapper there). nvm/node is intentionally omitted — it's versioned and
# brittle; a service needing a specific node should pin it via defaults.env.
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
    # None/"off" → HTTP-only gateway. "internal" → Caddy serves host routes over
    # HTTPS with its local CA (browsers get a secure context; trust the root CA).
    # "acme" → real Let's Encrypt wildcard cert (*.domain) via a DNS-01 challenge;
    # publicly trusted, no CA to install.
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


@dataclass
class CastleConfig:
    """Full castle configuration."""

    root: Path
    gateway: GatewayConfig
    repo: Path | None
    programs: dict[str, ProgramSpec]
    services: dict[str, ServiceSpec]
    jobs: dict[str, JobSpec]

    @property
    def tools(self) -> dict[str, ProgramSpec]:
        """Programs deployed as a PATH tool (a `runner: path` service) — derived
        from deployments, not the `behavior` label."""
        tool_programs = {
            s.program or n for n, s in self.services.items() if s.run.runner == "path"
        }
        return {k: v for k, v in self.programs.items() if k in tool_programs}

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

    - ``${secret:NAME}`` reads `~/.castle/secrets/NAME`.
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


def _read_secret(name: str) -> str:
    """Read a secret from ~/.castle/secrets/<name>. Returns placeholder if not found."""
    secret_path = SECRETS_DIR / name
    if secret_path.exists():
        return secret_path.read_text().strip()
    return f"<MISSING_SECRET:{name}>"


def _parse_program(name: str, data: dict) -> ProgramSpec:
    """Parse a programs: entry into a ProgramSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return ProgramSpec.model_validate(data_copy)


def _parse_service(name: str, data: dict) -> ServiceSpec:
    """Parse a services: entry into a ServiceSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return ServiceSpec.model_validate(data_copy)


def _parse_job(name: str, data: dict) -> JobSpec:
    """Parse a jobs: entry into a JobSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return JobSpec.model_validate(data_copy)


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


def load_config(root: Path | None = None) -> CastleConfig:
    """Load castle config: global castle.yaml + programs/, services/, jobs/ dirs."""
    if root is None:
        root = find_castle_root()

    config_path = root / "castle.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Castle config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    gateway_data = data.get("gateway", {})
    gateway = GatewayConfig(
        port=gateway_data.get("port", 9000),
        tls=gateway_data.get("tls"),
        domain=gateway_data.get("domain"),
        acme_email=gateway_data.get("acme_email"),
        acme_dns_provider=gateway_data.get("acme_dns_provider", "cloudflare"),
        public_domain=gateway_data.get("public_domain"),
        tunnel_id=gateway_data.get("tunnel_id"),
    )

    # repo: field points to the git repo for repo-relative sources
    repo_path: Path | None = None
    if data.get("repo"):
        repo_path = Path(data["repo"]).expanduser()

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

    services: dict[str, ServiceSpec] = {}
    for name, svc_data in _load_resource_dir(root / "services").items():
        services[name] = _parse_service(name, svc_data)

    jobs: dict[str, JobSpec] = {}
    for name, job_data in _load_resource_dir(root / "jobs").items():
        jobs[name] = _parse_job(name, job_data)

    return CastleConfig(
        root=root,
        repo=repo_path,
        gateway=gateway,
        programs=programs,
        services=services,
        jobs=jobs,
    )


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
    "proxy",
}


def _spec_to_yaml_dict(spec: ProgramSpec | ServiceSpec | JobSpec) -> dict:
    """Serialize a spec to a YAML-friendly dict, preserving structural presence."""
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
    return _clean_for_yaml(result)


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
    """Save castle config: global castle.yaml + programs/, services/, jobs/ dirs."""
    gateway_data: dict = {"port": config.gateway.port}
    if config.gateway.tls:
        gateway_data["tls"] = config.gateway.tls
    if config.gateway.domain:
        gateway_data["domain"] = config.gateway.domain
    if config.gateway.acme_email:
        gateway_data["acme_email"] = config.gateway.acme_email
    # Only persist the provider when non-default, to keep castle.yaml minimal.
    if config.gateway.acme_dns_provider and config.gateway.acme_dns_provider != "cloudflare":
        gateway_data["acme_dns_provider"] = config.gateway.acme_dns_provider
    data: dict = {"gateway": gateway_data}
    if config.repo:
        data["repo"] = str(config.repo)

    config_path = config.root / "castle.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    _write_resource_dir(
        config.root / "programs",
        {n: _program_to_yaml_dict(s, config) for n, s in config.programs.items()},
    )
    _write_resource_dir(
        config.root / "services",
        {n: _spec_to_yaml_dict(s) for n, s in config.services.items()},
    )
    _write_resource_dir(
        config.root / "jobs",
        {n: _spec_to_yaml_dict(s) for n, s in config.jobs.items()},
    )


def ensure_dirs() -> None:
    """Ensure castle directories exist."""
    CASTLE_HOME.mkdir(parents=True, exist_ok=True)
    CODE_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
    # Generated per-deployment secret env files (EnvironmentFile= / --env-file)
    # live here, kept out of unit files and process argv.
    secret_env_dir = SECRETS_DIR / "env"
    secret_env_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_env_dir, 0o700)
