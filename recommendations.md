# Scaling Recommendations

## 1. Extract a shared library

The same patterns are already duplicated in central-context and notification-bridge: `BaseSettings` with `.env`, FastAPI lifespan boilerplate, uvicorn entry points, error-to-HTTP-exception translation, test fixtures with temp dirs and settings overrides. At dozens of services this becomes a maintenance problem — fix a bug in the pattern and you're patching it everywhere.

A `castle-core` (or similar) package that provides a base settings class, standard lifespan wiring, common test fixtures, and health check endpoint would let new services start from ~10 lines of setup code.

## 2. Standardize project layout

Right now there are three different layouts: `src/central_context/`, flat `notification_bridge/`, and single-file `convert.py`. Pick one (the `src/` layout is the most robust) and stick with it. This matters because any top-level tooling that iterates over projects needs predictable structure.

## 3. Top-level task runner

With dozens of projects, there needs to be a way to run commands across all or some of them. A root `Makefile`, `justfile`, or script that can do things like:
- `make test` — run all tests
- `make test p=central-context` — run one project's tests
- `make lint` — lint everything
- `make sync` — `uv sync` in all projects

Without this, significant time gets spent just navigating and running repetitive commands.

## 4. Port and service registry

Ports are currently hardcoded defaults (9000, 9001). With dozens of services, there needs to be a single source of truth for port assignments — even if it's just a `services.yaml` at the repo root that maps service names to ports.

## 5. Inter-service configuration

notification-bridge hardcodes `http://localhost:9000` as the central-context URL. This pattern doesn't scale — each new service that talks to another service adds more hardcoded URLs in more `.env` files. Consider either:
- A convention like `CASTLE_{SERVICE_NAME}_URL` derived from the registry
- A shared config that generates per-service `.env` files

## 6. Consistent ruff/pyright configuration

Each project currently has its own ruff rules (devbox-connect selects `E,F,I,W` while mboxer selects `ALL`). With dozens of projects, either put a shared `ruff.toml` at the repo root (ruff walks up to find config) or decide on one standard. Same for pyright — only devbox-connect has it enabled currently.

## 7. What to defer

- **Containerization/orchestration** — until deploying somewhere beyond the local machine
- **API gateway / service mesh** — premature until there are actual traffic patterns
- **Distributed tracing / observability** — add when debugging cross-service issues becomes painful
- **Formal API schema sharing** (OpenAPI contracts between services) — FastAPI generates these already; formalize when there are consumers that need stability guarantees

## Priority

The highest-leverage first step is the shared library + top-level task runner, since those reduce the marginal cost of adding each new service.
