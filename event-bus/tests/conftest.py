"""Test fixtures for event-bus."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from event_bus.config import settings
from event_bus.main import app


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary data directory for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = settings.data_dir
    settings.data_dir = data_dir
    yield data_dir
    settings.data_dir = original


@pytest.fixture
def client(temp_data_dir: Path) -> Generator[TestClient, None, None]:
    """Create a test client with isolated data directory."""
    with TestClient(app) as client:
        yield client
