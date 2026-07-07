"""Integration tests for CastleNATSClient against a real NATS/JetStream broker.

Exercises the runtime the unit tests can't: connect, KV publish, peer discovery
via watch, presence, graceful-offline, and shared-config. Requires docker (the
`nats_url` fixture); skipped otherwise.
"""

from __future__ import annotations

import asyncio

import pytest
from castle_core.registry import Deployment, NodeConfig, NodeRegistry

import castle_api.nats_client as ncmod
from castle_api.mesh import mesh_state
from castle_api.nats_client import CastleNATSClient


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Stub the gateway-regen side effect (so tests never touch the host's real
    Caddyfile) and clear the shared mesh_state singleton around each test."""

    async def _stub(*_a, **_k):
        return False

    monkeypatch.setattr(ncmod, "refresh_remote_routes", _stub)
    mesh_state._nodes.clear()
    yield
    mesh_state._nodes.clear()


def _reg(host: str, deployed=None, role: str = "follower") -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(hostname=host, role=role), deployed=deployed or {}
    )


def _widget_reg(host: str) -> NodeRegistry:
    w = Deployment(
        manager="systemd", launcher="python", run_cmd=[], name="widget",
        kind="service", port=9099, subdomain="widget",
    )
    return _reg(host, {NodeRegistry.key("service", "widget"): w})


def test_publish_peer_discovery_and_offline(nats_url: str) -> None:
    async def run() -> None:
        a = CastleNATSClient("node-a", _reg("node-a"), servers=nats_url)
        b = CastleNATSClient("node-b", _widget_reg("node-b"), servers=nats_url)
        await a.start()
        await b.start()
        await asyncio.sleep(1.0)  # let watches propagate

        nodes = mesh_state.all_nodes(include_stale=True)
        assert "node-b" in nodes, "node-a should discover node-b via the KV watch"
        assert nodes["node-b"].registry.get("service", "widget") is not None

        # Graceful stop deletes b's key -> the DELETE watch marks it offline.
        await b.stop()
        await asyncio.sleep(1.0)
        nb = mesh_state.get_node("node-b")
        assert nb is None or not nb.online

        await a.stop()

    asyncio.run(run())


def test_presence_key_written(nats_url: str) -> None:
    async def run() -> None:
        c = CastleNATSClient("solo", _reg("solo"), servers=nats_url)
        await c.start()
        keys = await c._presence_kv.keys()
        assert "solo" in keys
        await c.stop()

    asyncio.run(run())


def test_shared_config_authority_write_read(nats_url: str) -> None:
    async def run() -> None:
        auth = CastleNATSClient("auth", _reg("auth", role="authority"), servers=nats_url)
        await auth.start()
        await auth.put_shared_config("fleet/motd", "hello")
        assert await auth.get_shared_config("fleet/motd") == "hello"
        assert "fleet/motd" in await auth.list_shared_config()
        await auth.stop()

    asyncio.run(run())


def test_secrets_never_on_the_wire(nats_url: str) -> None:
    """The registry a peer receives must carry no env/run_cmd."""
    async def run() -> None:
        secretful = Deployment(
            manager="systemd", launcher="python",
            run_cmd=["uv", "run", "svc"], env={"API_KEY": "s3cr3t"},
            name="svc", kind="service", port=9001, subdomain="svc",
        )
        a = CastleNATSClient("wa", _reg("wa"), servers=nats_url)
        b = CastleNATSClient(
            "wb", _reg("wb", {NodeRegistry.key("service", "svc"): secretful}),
            servers=nats_url,
        )
        await a.start()
        await b.start()
        await asyncio.sleep(1.0)
        svc = mesh_state.get_node("wb").registry.get("service", "svc")
        assert svc is not None
        assert not svc.env, "env must not cross the wire"
        assert not svc.run_cmd, "run_cmd must not cross the wire"
        await a.stop()
        await b.stop()

    asyncio.run(run())
