"""Event bus core — in-memory subscription table and HTTP fan-out delivery."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    """A subscription to a topic."""

    topic: str
    callback_url: str
    subscriber: str = ""  # optional label for debugging


@dataclass
class EventBus:
    """In-memory event bus with HTTP fan-out delivery."""

    subscriptions: dict[str, list[Subscription]] = field(default_factory=dict)
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def subscribe(self, topic: str, callback_url: str, subscriber: str = "") -> None:
        """Register a subscription to a topic."""
        if topic not in self.subscriptions:
            self.subscriptions[topic] = []

        # Don't duplicate
        for sub in self.subscriptions[topic]:
            if sub.callback_url == callback_url:
                return

        self.subscriptions[topic].append(
            Subscription(topic=topic, callback_url=callback_url, subscriber=subscriber)
        )
        logger.info("Subscribed %s to topic '%s' -> %s", subscriber, topic, callback_url)

    def unsubscribe(self, topic: str, callback_url: str) -> bool:
        """Remove a subscription. Returns True if found and removed."""
        if topic not in self.subscriptions:
            return False

        before = len(self.subscriptions[topic])
        self.subscriptions[topic] = [
            s for s in self.subscriptions[topic] if s.callback_url != callback_url
        ]
        removed = len(self.subscriptions[topic]) < before

        if not self.subscriptions[topic]:
            del self.subscriptions[topic]

        return removed

    async def publish(self, topic: str, payload: dict) -> int:
        """Publish an event to all subscribers. Returns number of subscribers notified."""
        subscribers = self.subscriptions.get(topic, [])
        if not subscribers:
            return 0

        event = {
            "topic": topic,
            "payload": payload,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        # Fan out to all subscribers concurrently, fire-and-forget style
        tasks = [self._deliver(sub, event) for sub in subscribers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        delivered = sum(1 for r in results if r is True)
        return delivered

    async def _deliver(self, sub: Subscription, event: dict) -> bool:
        """Deliver an event to a single subscriber."""
        if not self._client:
            logger.error("HTTP client not initialized")
            return False

        try:
            response = await self._client.post(sub.callback_url, json=event)
            if response.status_code < 300:
                return True
            logger.warning(
                "Delivery to %s returned %d", sub.callback_url, response.status_code
            )
            return False
        except Exception:
            logger.warning("Delivery to %s failed", sub.callback_url, exc_info=True)
            return False

    def list_topics(self) -> dict[str, list[dict]]:
        """List all topics and their subscribers."""
        return {
            topic: [
                {"callback_url": s.callback_url, "subscriber": s.subscriber}
                for s in subs
            ]
            for topic, subs in self.subscriptions.items()
        }


# Singleton instance
bus = EventBus()
