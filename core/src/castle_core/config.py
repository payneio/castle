"""Castle configuration and registry management."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from castle_core.manifest import (
    CaddySpec,
    DefaultsSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    JobSpec,
    ManageSpec,
    ProgramSpec,
    ProxySpec,
    RunCommand,
    RunPython,
    ServiceSpec,
    SystemdSpec,
    UnitKind,
    UnitSpec,
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
        "Could not find castle.yaml.\n"
        f"Expected at: {CASTLE_HOME / 'castle.yaml'}"
    )


@dataclass
class GatewayConfig:
    """Gateway configuration."""

    port: int = 9000


@dataclass
class CastleConfig:
    """Full castle configuration."""

    root: Path
    gateway: GatewayConfig
    repo: Path | None
    programs: dict[str, ProgramSpec]
    services: dict[str, ServiceSpec]
    jobs: dict[str, JobSpec]
    _unit_names: set[str] = field(default_factory=set)
    _units_raw: dict[str, dict] = field(default_factory=dict)

    @property
    def tools(self) -> dict[str, ProgramSpec]:
        """Return programs that are tools (behavior == 'tool')."""
        return {
            k: v
            for k, v in self.programs.items()
            if v.behavior == "tool"
        }

    @property
    def frontends(self) -> dict[str, ProgramSpec]:
        """Return programs that are frontends (have build outputs)."""
        return {
            k: v
            for k, v in self.programs.items()
            if v.build and (v.build.outputs or v.build.commands)
        }


def resolve_env_vars(env: dict[str, str]) -> dict[str, str]:
    """Resolve ${secret:NAME} references in env values."""
    resolved = {}
    for key, value in env.items():

        def replace_var(match: re.Match[str]) -> str:
            ref = match.group(1)
            if ref.startswith("secret:"):
                secret_name = ref[7:]
                return _read_secret(secret_name)
            return match.group(0)

        resolved[key] = re.sub(r"\$\{([^}]+)\}", replace_var, value)
    return resolved


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


def _parse_unit(name: str, data: dict) -> UnitSpec:
    """Parse a units: entry into a UnitSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return UnitSpec.model_validate(data_copy)


# Stack convention defaults used during unit expansion.
_STACK_DEFAULTS: dict[str, dict[str, str]] = {
    "python-fastapi": {"runner": "python", "health_path": "/health"},
    "python-cli": {"runner": "command"},
    "react-vite": {},
}

# Kind → ProgramSpec.behavior mapping.
_KIND_BEHAVIOR: dict[str, str] = {
    "tool": "tool",
    "service": "daemon",
    "site": "frontend",
    "job": "tool",
}


def _expand_units(
    units: dict[str, UnitSpec],
    programs: dict[str, ProgramSpec],
    services: dict[str, ServiceSpec],
    jobs: dict[str, JobSpec],
) -> None:
    """Expand units: entries into programs/services/jobs dicts (in-place)."""
    for name, unit in units.items():
        if name in programs or name in services or name in jobs:
            raise ValueError(
                f"Unit '{name}' conflicts with existing entry in "
                f"programs/services/jobs"
            )

        defaults = _STACK_DEFAULTS.get(unit.stack or "", {})

        # Always create a ProgramSpec
        programs[name] = ProgramSpec(
            id=name,
            description=unit.description,
            behavior=_KIND_BEHAVIOR[unit.kind.value],
            source=unit.source,
            stack=unit.stack,
            system_dependencies=unit.system_dependencies,
            install_extras=unit.install_extras,
            version=unit.version,
            build=unit.build,
            tags=unit.tags,
        )

        if unit.kind == UnitKind.SERVICE:
            assert unit.port is not None  # guaranteed by validator
            runner = defaults.get("runner", "python")
            run_spec: RunCommand | RunPython
            if runner == "python":
                run_spec = RunPython(runner="python", program=name)
            else:
                run_spec = RunCommand(runner="command", argv=[name])

            health = unit.health_path or defaults.get("health_path")

            services[name] = ServiceSpec(
                id=name,
                program=name,
                run=run_spec,
                expose=ExposeSpec(
                    http=HttpExposeSpec(
                        internal=HttpInternal(port=unit.port),
                        health_path=health,
                    )
                ),
                proxy=ProxySpec(caddy=CaddySpec(path_prefix=unit.path_prefix))
                if unit.path_prefix
                else None,
                manage=ManageSpec(systemd=SystemdSpec()),
                defaults=DefaultsSpec(env=dict(unit.env)) if unit.env else None,
            )

        elif unit.kind == UnitKind.JOB:
            assert unit.schedule is not None  # guaranteed by validator
            assert unit.argv is not None  # guaranteed by validator
            jobs[name] = JobSpec(
                id=name,
                program=name,
                description=unit.description,
                run=RunCommand(runner="command", argv=list(unit.argv)),
                schedule=unit.schedule,
                timezone=unit.timezone,
                manage=ManageSpec(systemd=SystemdSpec()),
                defaults=DefaultsSpec(env=dict(unit.env)) if unit.env else None,
            )


def load_config(root: Path | None = None) -> CastleConfig:
    """Load castle.yaml and return parsed configuration."""
    if root is None:
        root = find_castle_root()

    config_path = root / "castle.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Castle config not found: {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    gateway_data = data.get("gateway", {})
    gateway = GatewayConfig(port=gateway_data.get("port", 9000))

    # repo: field points to the git repo for repo-relative sources
    repo_path: Path | None = None
    if data.get("repo"):
        repo_path = Path(data["repo"]).expanduser()

    programs: dict[str, ProgramSpec] = {}
    # Support both "programs:" and legacy "components:" key
    programs_data = data.get("programs") or data.get("components") or {}
    for name, comp_data in programs_data.items():
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
    for name, svc_data in data.get("services", {}).items():
        services[name] = _parse_service(name, svc_data)

    jobs: dict[str, JobSpec] = {}
    for name, job_data in data.get("jobs", {}).items():
        jobs[name] = _parse_job(name, job_data)

    # Expand units: section into programs/services/jobs
    units_data = data.get("units") or {}
    units: dict[str, UnitSpec] = {}
    for name, unit_data in units_data.items():
        units[name] = _parse_unit(name, unit_data)

    unit_names: set[str] = set()
    if units:
        _expand_units(units, programs, services, jobs)
        unit_names = set(units.keys())
        # Resolve source paths for unit-generated programs
        for name in unit_names:
            prog = programs[name]
            if prog.source:
                if prog.source.startswith("repo:") and repo_path:
                    prog.source = str(repo_path / prog.source[5:])
                elif not Path(prog.source).is_absolute():
                    prog.source = str(root / prog.source)

    return CastleConfig(
        root=root,
        repo=repo_path,
        gateway=gateway,
        programs=programs,
        services=services,
        jobs=jobs,
        _unit_names=unit_names,
        _units_raw=dict(units_data),
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
    "caddy",
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


def save_config(config: CastleConfig) -> None:
    """Save castle configuration to castle.yaml."""
    data: dict = {"gateway": {"port": config.gateway.port}}

    if config.repo:
        data["repo"] = str(config.repo)

    # Write units: section (raw roundtrip preserves user's original YAML)
    if config._units_raw:
        data["units"] = dict(config._units_raw)

    # Write programs: (excluding unit-expanded ones)
    non_unit_programs = {
        k: v for k, v in config.programs.items() if k not in config._unit_names
    }
    if non_unit_programs:
        data["programs"] = {}
        for name, spec in non_unit_programs.items():
            d = _spec_to_yaml_dict(spec)
            # Store relative source paths in YAML
            if d.get("source") and Path(d["source"]).is_absolute():
                src = Path(d["source"])
                # If source is under repo, store as repo:relative
                if config.repo:
                    try:
                        d["source"] = "repo:" + str(src.relative_to(config.repo))
                        data["programs"][name] = d
                        continue
                    except ValueError:
                        pass
                # Otherwise store relative to config root
                try:
                    d["source"] = str(src.relative_to(config.root))
                except ValueError:
                    pass  # not under root — keep absolute
            data["programs"][name] = d

    # Write services: (excluding unit-expanded ones)
    non_unit_services = {
        k: v for k, v in config.services.items() if k not in config._unit_names
    }
    if non_unit_services:
        data["services"] = {}
        for name, spec in non_unit_services.items():
            data["services"][name] = _spec_to_yaml_dict(spec)

    # Write jobs: (excluding unit-expanded ones)
    non_unit_jobs = {
        k: v for k, v in config.jobs.items() if k not in config._unit_names
    }
    if non_unit_jobs:
        data["jobs"] = {}
        for name, spec in non_unit_jobs.items():
            data["jobs"][name] = _spec_to_yaml_dict(spec)

    config_path = config.root / "castle.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def ensure_dirs() -> None:
    """Ensure castle directories exist."""
    CASTLE_HOME.mkdir(parents=True, exist_ok=True)
    CODE_DIR.mkdir(parents=True, exist_ok=True)
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
