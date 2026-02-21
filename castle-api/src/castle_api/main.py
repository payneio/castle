"""Castle API — dashboard data, health aggregation, and service management."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from castle_api.config import settings
from castle_api.config_editor import router as config_router
from castle_api.logs import router as logs_router
from castle_api.routes import router as dashboard_router
from castle_api.secrets import router as secrets_router
from castle_api.services import router as services_router
from castle_api.stream import close_all_subscribers, health_poll_loop, subscribe, unsubscribe
from castle_api.tools import router as tools_router

# Set by _watch_shutdown when uvicorn begins its shutdown sequence.
_shutting_down = False


async def _watch_shutdown(server: uvicorn.Server) -> None:
    """Poll uvicorn's should_exit flag and close SSE subscribers promptly."""
    while not server.should_exit:
        await asyncio.sleep(0.5)
    global _shutting_down
    _shutting_down = True
    close_all_subscribers()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    global _shutting_down
    _shutting_down = False

    poll_task = asyncio.create_task(health_poll_loop())

    yield

    _shutting_down = True
    poll_task.cancel()
    close_all_subscribers()


app = FastAPI(
    title="castle-api",
    description="Castle API and service management",
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
app.include_router(logs_router)
app.include_router(secrets_router)
app.include_router(services_router)
app.include_router(tools_router)


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
                if not msg:
                    break
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
    config = uvicorn.Config(
        "castle_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    server = uvicorn.Server(config)

    async def serve_with_watcher() -> None:
        watcher = asyncio.create_task(_watch_shutdown(server))
        await server.serve()
        watcher.cancel()

    asyncio.run(serve_with_watcher())


if __name__ == "__main__":
    run()
