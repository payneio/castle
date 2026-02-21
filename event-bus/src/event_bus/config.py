"""Configuration for event-bus."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables."""

    data_dir: Path = Path("./data")
    host: str = "0.0.0.0"
    port: int = 9010

    model_config = {
        "env_prefix": "EVENT_BUS_",
        "env_file": ".env",
    }

    def ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
