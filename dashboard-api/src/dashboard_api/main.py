"""Castle API — dashboard data, health aggregation, event bus, service management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from dashboard_api.bus import bus
from dashboard_api.config import settings
from dashboard_api.config_editor import router as config_router
from dashboard_api.events import router as events_router
from dashboard_api.logs import router as logs_router
from dashboard_api.routes import router as dashboard_router
from dashboard_api.secrets import router as secrets_router
from dashboard_api.services import router as services_router
from dashboard_api.stream import health_poll_loop, subscribe, unsubscribe


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    await bus.start()
    poll_task = asyncio.create_task(health_poll_loop())
    yield
    poll_task.cancel()
    await bus.stop()


app = FastAPI(
    title="Castle API",
    description="Castle dashboard API, event bus, and service management",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(dashboard_router)
app.include_router(events_router)
app.include_router(logs_router)
app.include_router(secrets_router)
app.include_router(services_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/stream")
async def sse_stream() -> StreamingResponse:
    """SSE stream — pushes health updates and service action events."""
    q = subscribe()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                msg = await q.get()
                yield msg
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def run() -> None:
    """Run the application with uvicorn."""
    uvicorn.run(
        "dashboard_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
