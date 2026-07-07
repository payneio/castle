"""CastleNATSClient role gating — hermetic (no live NATS server needed).

The write-gate is checked before touching the KV bucket, so a follower is denied
without any connection.
"""

from __future__ import annotations

import asyncio

import pytest
from castle_core.registry import NodeConfig, NodeRegistry

from castle_api.nats_client import CastleNATSClient


def _client(role: str) -> CastleNATSClient:
    reg = NodeRegistry(node=NodeConfig(hostname="n", role=role), deployed={})
    return CastleNATSClient("n", reg, servers="nats://localhost:4222")


def test_role_property() -> None:
    assert _client("authority").role == "authority"
    assert _client("follower").role == "follower"


def test_follower_cannot_write_shared_config() -> None:
    client = _client("follower")
    with pytest.raises(PermissionError):
        asyncio.run(client.put_shared_config("fleet/key", "value"))
