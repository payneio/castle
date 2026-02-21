"""Configuration for castle-api."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables."""

    castle_root: Path = Path("/data/repos/castle")
    host: str = "0.0.0.0"
    port: int = 9020

    model_config = {
        "env_prefix": "CASTLE_API_",
        "env_file": ".env",
    }


settings = Settings()
