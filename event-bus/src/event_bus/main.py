"""Main application for event-bus.

A lightweight castle-component for inter-service communication.
Services publish typed events, other services subscribe with webhook callbacks.
The bus delivers events via HTTP POST fan-out. No persistence, no guaranteed delivery.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from event_bus.bus import bus
from event_bus.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    settings.ensure_data_dir()
    await bus.start()
    yield
    await bus.stop()


app = FastAPI(
    title="event-bus",
    description="Inter-service event bus for castle",
    version="0.1.0",
    lifespan=lifespan,
)


class PublishRequest(BaseModel):
    """Request body for publishing an event."""

    topic: str
    payload: dict


class SubscribeRequest(BaseModel):
    """Request body for subscribing to a topic."""

    topic: str
    callback_url: str
    subscriber: str = ""


class UnsubscribeRequest(BaseModel):
    """Request body for unsubscribing from a topic."""

    topic: str
    callback_url: str


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/publish")
async def publish(request: PublishRequest) -> dict:
    """Publish an event to a topic. Returns number of subscribers notified."""
    delivered = await bus.publish(request.topic, request.payload)
    return {
        "topic": request.topic,
        "subscribers_notified": delivered,
    }


@app.post("/subscribe")
async def subscribe(request: SubscribeRequest) -> dict:
    """Subscribe to a topic with a webhook callback URL."""
    bus.subscribe(request.topic, request.callback_url, request.subscriber)
    return {
        "topic": request.topic,
        "callback_url": request.callback_url,
        "status": "subscribed",
    }


@app.post("/unsubscribe")
async def unsubscribe(request: UnsubscribeRequest) -> dict:
    """Unsubscribe from a topic."""
    removed = bus.unsubscribe(request.topic, request.callback_url)
    return {
        "topic": request.topic,
        "callback_url": request.callback_url,
        "status": "unsubscribed" if removed else "not_found",
    }


@app.get("/topics")
async def list_topics() -> dict:
    """List all topics and their subscribers."""
    return {"topics": bus.list_topics()}


def run() -> None:
    """Run the application with uvicorn."""
    uvicorn.run(
        "event_bus.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
