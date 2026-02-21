"""Tests for event bus publish/subscribe functionality."""

from fastapi.testclient import TestClient

from event_bus.bus import EventBus


class TestSubscribe:
    """Subscription management tests."""

    def test_subscribe(self, client: TestClient) -> None:
        """Subscribe to a topic."""
        response = client.post(
            "/subscribe",
            json={
                "topic": "test.event",
                "callback_url": "http://localhost:9999/hook",
                "subscriber": "test-service",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "subscribed"
        assert data["topic"] == "test.event"

    def test_subscribe_deduplicates(self, client: TestClient) -> None:
        """Same callback URL for same topic is not duplicated."""
        for _ in range(3):
            client.post(
                "/subscribe",
                json={
                    "topic": "test.event",
                    "callback_url": "http://localhost:9999/hook",
                },
            )

        response = client.get("/topics")
        topics = response.json()["topics"]
        assert len(topics.get("test.event", [])) == 1

    def test_unsubscribe(self, client: TestClient) -> None:
        """Unsubscribe removes the subscription."""
        client.post(
            "/subscribe",
            json={
                "topic": "test.event",
                "callback_url": "http://localhost:9999/hook",
            },
        )

        response = client.post(
            "/unsubscribe",
            json={
                "topic": "test.event",
                "callback_url": "http://localhost:9999/hook",
            },
        )
        assert response.json()["status"] == "unsubscribed"

        response = client.get("/topics")
        assert "test.event" not in response.json()["topics"]

    def test_unsubscribe_not_found(self, client: TestClient) -> None:
        """Unsubscribing from non-existent subscription returns not_found."""
        response = client.post(
            "/unsubscribe",
            json={
                "topic": "nonexistent",
                "callback_url": "http://localhost:9999/hook",
            },
        )
        assert response.json()["status"] == "not_found"


class TestPublish:
    """Event publishing tests."""

    def test_publish_no_subscribers(self, client: TestClient) -> None:
        """Publishing to a topic with no subscribers returns 0."""
        response = client.post(
            "/publish",
            json={"topic": "empty.topic", "payload": {"msg": "hello"}},
        )
        assert response.status_code == 200
        assert response.json()["subscribers_notified"] == 0


class TestTopics:
    """Topic listing tests."""

    def test_list_topics_empty(self, client: TestClient) -> None:
        """Empty bus returns empty topics."""
        response = client.get("/topics")
        assert response.status_code == 200
        assert response.json() == {"topics": {}}

    def test_list_topics_with_subscriptions(self, client: TestClient) -> None:
        """Topics list shows all subscriptions."""
        client.post(
            "/subscribe",
            json={
                "topic": "a.event",
                "callback_url": "http://localhost:9999/a",
                "subscriber": "svc-a",
            },
        )
        client.post(
            "/subscribe",
            json={
                "topic": "b.event",
                "callback_url": "http://localhost:9999/b",
                "subscriber": "svc-b",
            },
        )

        response = client.get("/topics")
        topics = response.json()["topics"]
        assert "a.event" in topics
        assert "b.event" in topics
        assert topics["a.event"][0]["subscriber"] == "svc-a"


class TestEventBusUnit:
    """Unit tests for the EventBus class."""

    def test_subscribe_and_list(self) -> None:
        """Subscribe adds to subscription table."""
        eb = EventBus()
        eb.subscribe("test", "http://localhost/hook", "test-svc")
        topics = eb.list_topics()
        assert "test" in topics
        assert topics["test"][0]["callback_url"] == "http://localhost/hook"

    def test_unsubscribe_cleans_empty_topic(self) -> None:
        """Unsubscribing the last subscriber removes the topic."""
        eb = EventBus()
        eb.subscribe("test", "http://localhost/hook")
        eb.unsubscribe("test", "http://localhost/hook")
        assert "test" not in eb.list_topics()
