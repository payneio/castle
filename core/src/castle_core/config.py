"""Castle configuration and registry management."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from castle_core.manifest import ComponentSpec, JobSpec, ServiceSpec


def find_castle_root() -> Path:
    """Find the castle repository root by walking up from cwd looking for castle.yaml."""
    current = Path.cwd()
    while current != current.parent:
        if (current / "castle.yaml").exists():
            return current
        current = current.parent
    # Fallback: check if castle.yaml is in a well-known location
    default = Path("/data/repos/castle")
    if (default / "castle.yaml").exists():
        return default
    raise FileNotFoundError(
        "Could not find castle.yaml. Run castle from within the castle repository."
    )


CASTLE_HOME = Path.home() / ".castle"
GENERATED_DIR = CASTLE_HOME / "generated"
SECRETS_DIR = CASTLE_HOME / "secrets"
STATIC_DIR = CASTLE_HOME / "static"


@dataclass
class GatewayConfig:
    """Gateway configuration."""

    port: int = 9000


@dataclass
class CastleConfig:
    """Full castle configuration."""

    root: Path
    gateway: GatewayConfig
    components: dict[str, ComponentSpec]
    services: dict[str, ServiceSpec]
    jobs: dict[str, JobSpec]

    @property
    def tools(self) -> dict[str, ComponentSpec]:
        """Return components that are tools (have install.path or tool spec)."""
        return {
            k: v
            for k, v in self.components.items()
            if (v.install and v.install.path) or v.tool
        }

    @property
    def frontends(self) -> dict[str, ComponentSpec]:
        """Return components that are frontends (have build outputs)."""
        return {
            k: v
            for k, v in self.components.items()
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


def _parse_component(name: str, data: dict) -> ComponentSpec:
    """Parse a components: entry into a ComponentSpec."""
    data_copy = dict(data)
    data_copy["id"] = name
    return ComponentSpec.model_validate(data_copy)


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

    components: dict[str, ComponentSpec] = {}
    for name, comp_data in data.get("components", {}).items():
        components[name] = _parse_component(name, comp_data)

    services: dict[str, ServiceSpec] = {}
    for name, svc_data in data.get("services", {}).items():
        services[name] = _parse_service(name, svc_data)

    jobs: dict[str, JobSpec] = {}
    for name, job_data in data.get("jobs", {}).items():
        jobs[name] = _parse_job(name, job_data)

    return CastleConfig(
        root=root,
        gateway=gateway,
        components=components,
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
    "install",
    "path",
    "tool",
    "expose",
    "proxy",
    "caddy",
}


def _spec_to_yaml_dict(spec: ComponentSpec | ServiceSpec | JobSpec) -> dict:
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

    if config.components:
        data["components"] = {}
        for name, spec in config.components.items():
            data["components"][name] = _spec_to_yaml_dict(spec)

    if config.services:
        data["services"] = {}
        for name, spec in config.services.items():
            data["services"][name] = _spec_to_yaml_dict(spec)

    if config.jobs:
        data["jobs"] = {}
        for name, spec in config.jobs.items():
            data["jobs"][name] = _spec_to_yaml_dict(spec)

    config_path = config.root / "castle.yaml"
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def ensure_dirs() -> None:
    """Ensure castle directories exist."""
    CASTLE_HOME.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS_DIR, 0o700)
