"""Event bus API routes — subscribe, publish, unsubscribe, list topics."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from castle_api.bus import bus

router = APIRouter(prefix="/events", tags=["events"])


class PublishRequest(BaseModel):
    topic: str
    payload: dict


class SubscribeRequest(BaseModel):
    topic: str
    callback_url: str
    subscriber: str = ""


class UnsubscribeRequest(BaseModel):
    topic: str
    callback_url: str


@router.post("/publish")
async def publish(request: PublishRequest) -> dict:
    """Publish an event to a topic."""
    delivered = await bus.publish(request.topic, request.payload)
    return {"topic": request.topic, "subscribers_notified": delivered}


@router.post("/subscribe")
async def subscribe(request: SubscribeRequest) -> dict:
    """Subscribe to a topic with a webhook callback URL."""
    bus.subscribe(request.topic, request.callback_url, request.subscriber)
    return {
        "topic": request.topic,
        "callback_url": request.callback_url,
        "status": "subscribed",
    }


@router.post("/unsubscribe")
async def unsubscribe(request: UnsubscribeRequest) -> dict:
    """Unsubscribe from a topic."""
    removed = bus.unsubscribe(request.topic, request.callback_url)
    return {
        "topic": request.topic,
        "callback_url": request.callback_url,
        "status": "unsubscribed" if removed else "not_found",
    }


@router.get("/topics")
async def list_topics() -> dict:
    """List all topics and their subscribers."""
    return {"topics": bus.list_topics()}
