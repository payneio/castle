"""Configuration for castle-api."""

from pathlib import Path

from pydantic_settings import BaseSettings

from castle_core.config import CastleConfig, load_config
from castle_core.registry import NodeRegistry, load_registry


class Settings(BaseSettings):
    """Service settings loaded from environment variables."""

    host: str = "0.0.0.0"
    port: int = 9020

    model_config = {
        "env_prefix": "CASTLE_API_",
        "env_file": ".env",
    }


settings = Settings()


def get_registry() -> NodeRegistry:
    """Load the node registry. Raises if not found."""
    return load_registry()


def get_castle_root() -> Path | None:
    """Get the castle repo root from the registry, if available."""
    try:
        registry = load_registry()
        if registry.node.castle_root:
            return Path(registry.node.castle_root)
    except (FileNotFoundError, ValueError):
        pass
    return None


def get_config() -> CastleConfig:
    """Load castle.yaml via the registry's castle_root.

    Raises FileNotFoundError if repo not available.
    """
    root = get_castle_root()
    if root is None:
        raise FileNotFoundError(
            "Castle repo not available. Set castle_root in registry."
        )
    return load_config(root)
