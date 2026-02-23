# Web APIs in Castle

How to build Python web APIs as castle service components. Based on the
patterns used in [wild-cloud/api](https://github.com/civilsociety-dev/wild-cloud)
and existing castle services (central-context, notification-bridge, event-bus).

## Stack

| Layer | Choice |
|-------|--------|
| **Framework** | FastAPI |
| **Server** | uvicorn |
| **Config** | pydantic-settings (env vars) |
| **Validation** | Pydantic models |
| **HTTP client** | httpx (async) |
| **Testing** | pytest + FastAPI TestClient |
| **Python** | 3.13+ for services |

## Project layout

```
my-service/
├── src/my_service/
│   ├── __init__.py        # Package version
│   ├── main.py            # FastAPI app, lifespan, entry point
│   ├── config.py          # pydantic-settings
│   ├── models.py          # Request/response Pydantic models
│   ├── routes.py          # APIRouter with endpoints
│   └── storage.py         # Domain logic (no FastAPI imports)
├── tests/
│   ├── conftest.py        # Fixtures (client, temp dirs)
│   ├── test_api.py        # Endpoint integration tests
│   └── test_storage.py    # Domain unit tests
├── pyproject.toml
└── CLAUDE.md
```

Separation of concerns: routes handle HTTP, storage/core handles logic,
models define schemas. Domain code never imports FastAPI.

## pyproject.toml

```toml
[project]
name = "my-service"
version = "0.1.0"
description = "Does something useful"
requires-python = ">=3.13"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "pydantic-settings>=2.0.0",
]

[project.scripts]
my-service = "my_service.main:run"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_service"]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "httpx>=0.28.0",
]
```

## Configuration

Use pydantic-settings with an env prefix matching the service name:

```python
# config.py
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: Path = Path("./data")
    host: str = "0.0.0.0"
    port: int = 9001

    model_config = {
        "env_prefix": "MY_SERVICE_",
        "env_file": ".env",
    }

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
```

Castle passes config via env vars in castle.yaml:

```yaml
components:
  my-service:
    description: Does something useful
    source: components/my-service

services:
  my-service:
    component: my-service
    run:
      runner: python
      tool: my-service
    expose:
      http:
        internal: { port: 9001 }
        health_path: /health
    proxy:
      caddy: { path_prefix: /my-service }
    manage:
      systemd: {}
```

Convention-based env vars (`MY_SERVICE_DATA_DIR`, `MY_SERVICE_PORT`) are
generated automatically by `castle deploy`. Only non-convention values
need `defaults.env`:

```yaml
    defaults:
      env:
        CENTRAL_CONTEXT_URL: http://localhost:9001
```

## Application entry point

```python
# main.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from my_service.config import settings
from my_service.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.ensure_data_dir()
    yield


app = FastAPI(
    title="my-service",
    description="Does something useful",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run() -> None:
    uvicorn.run(
        "my_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
```

For services with async resources (HTTP clients, connections), initialize
them in the lifespan and clean up after yield:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings.ensure_data_dir()
    async with httpx.AsyncClient(timeout=10.0) as client:
        app.state.http_client = client
        yield
```

## Routes

Use APIRouter with a prefix and tags. Map domain exceptions to HTTP status codes.

```python
# routes.py
from fastapi import APIRouter, HTTPException, status

from my_service.models import ItemCreate, ItemResponse
from my_service.storage import (
    ItemExistsError,
    ItemNotFoundError,
    create_item,
    get_item,
    list_items,
)

router = APIRouter(prefix="/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
def create(request: ItemCreate) -> ItemResponse:
    try:
        return create_item(request)
    except ItemExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/{item_id}", response_model=ItemResponse)
def get(item_id: str) -> ItemResponse:
    try:
        return get_item(item_id)
    except ItemNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("", response_model=list[ItemResponse])
def list_all() -> list[ItemResponse]:
    return list_items()
```

## Request/response models

Separate create models (what the client sends) from response models (what
comes back). Use inheritance to avoid repetition.

```python
# models.py
from datetime import datetime
from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    name: str = Field(..., description="Item name")
    content: str = Field(..., description="Item content")
    description: str | None = Field(default=None)


class ItemResponse(BaseModel):
    name: str
    description: str | None
    created_at: datetime
    size_bytes: int
    checksum: str


class ItemWithBody(ItemResponse):
    content: str
```

## Error handling

Define domain exceptions in the storage/core layer. Map them to HTTP status
codes in the route layer.

```python
# storage.py
class StorageError(Exception):
    pass

class ItemExistsError(StorageError):
    pass

class ItemNotFoundError(StorageError):
    pass

class InvalidNameError(StorageError):
    pass
```

Mapping convention:

| Exception | HTTP Status |
|-----------|-------------|
| `NotFoundError` | 404 |
| `ExistsError` / conflict | 409 |
| `InvalidError` / bad input | 400 |
| Unexpected | 500 (FastAPI default) |

## Storage

Castle services use filesystem storage with JSON metadata sidecars:

```
/data/castle/my-service/
└── bucket/
    ├── item-name
    └── item-name.meta.json
```

```python
# storage.py
import hashlib
import json
from datetime import datetime
from pathlib import Path

from my_service.config import settings
from my_service.models import ItemCreate, ItemResponse


def create_item(request: ItemCreate) -> ItemResponse:
    checksum = hashlib.sha256(request.content.encode()).hexdigest()
    path = settings.data_dir / request.name
    meta_path = path.with_suffix(path.suffix + ".meta.json")

    if path.exists():
        raise ItemExistsError(f"'{request.name}' already exists")

    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    metadata = ItemResponse(
        name=request.name,
        description=request.description,
        created_at=now,
        size_bytes=len(request.content.encode()),
        checksum=checksum,
    )

    path.write_text(request.content, encoding="utf-8")
    meta_path.write_text(
        json.dumps(metadata.model_dump(), default=str, indent=2)
    )
    return metadata
```

## Testing

### Fixtures

```python
# tests/conftest.py
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from my_service import config
from my_service.main import app


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Generator[Path, None, None]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = config.settings.data_dir
    config.settings.data_dir = data_dir
    yield data_dir
    config.settings.data_dir = original


@pytest.fixture
def client(temp_data_dir: Path) -> Generator[TestClient, None, None]:
    with TestClient(app) as client:
        yield client
```

### Endpoint tests

```python
# tests/test_api.py
from fastapi import status
from fastapi.testclient import TestClient


class TestHealth:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}


class TestCreateItem:
    def test_create(self, client: TestClient) -> None:
        response = client.post(
            "/items",
            json={"name": "test", "content": "hello"},
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "test"
        assert "checksum" in data

    def test_duplicate_returns_409(self, client: TestClient) -> None:
        payload = {"name": "dup", "content": "hello"}
        client.post("/items", json=payload)
        response = client.post("/items", json=payload)
        assert response.status_code == status.HTTP_409_CONFLICT
```

### Domain unit tests

```python
# tests/test_storage.py
from pathlib import Path

from my_service.models import ItemCreate
from my_service.storage import create_item


class TestCreateItem:
    def test_creates_files(self, temp_data_dir: Path) -> None:
        request = ItemCreate(name="test", content="hello")
        metadata = create_item(request)

        assert metadata.name == "test"
        assert (temp_data_dir / "test").exists()
        assert (temp_data_dir / "test.meta.json").exists()
```

## Commands

```bash
uv sync                     # Install deps
uv run my-service           # Run service
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Scaffolding

`castle create` generates all of this automatically:

```bash
castle create my-service --type service --description "Does something useful"
```

See @docs/component-registry.md for manifest fields, role derivation, and
the full service lifecycle (enable, logs, gateway reload).
