"""NATS JetStream client for inter-node mesh coordination.

Replaces the MQTT transport. State lives in a JetStream **KV bucket** rather than
retained MQTT messages:

  castle-registry  — key=<hostname>, value=secret-stripped NodeRegistry JSON

Lifecycle:
  * on connect: ensure the bucket, PUT our registry, seed local state from every
    existing key, then watch the bucket for peer changes.
  * heartbeat: re-PUT our registry every HEARTBEAT_SEC so peers refresh their
    last-seen clock (crash liveness rides the existing stale-TTL).
  * graceful stop: DELETE our key → peers get an immediate offline signal.

Being asyncio-native, the watch callback calls ``broadcast`` directly — no
cross-thread ``run_coroutine_threadsafe`` hop (which the paho client needed).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import nats
from nats.js.api import KeyValueConfig

from castle_core.registry import NodeRegistry

from castle_api.mesh import mesh_state
from castle_api.mesh_wire import json_to_registry, registry_to_json
from castle_api.stream import broadcast

logger = logging.getLogger(__name__)

REGISTRY_BUCKET = "castle-registry"
HEARTBEAT_SEC = 30.0
PRUNE_SEC = 30.0


class CastleNATSClient:
    """Async NATS/JetStream mesh client."""

    def __init__(
        self,
        local_hostname: str,
        local_registry: NodeRegistry,
        servers: str | list[str] = "nats://localhost:4222",
    ) -> None:
        self._local_hostname = local_hostname
        self._local_registry = local_registry
        self._servers = servers
        self._nc: nats.NATS | None = None
        self._kv = None
        self._tasks: list[asyncio.Task] = []
        self._last_json: dict[str, str] = {}
        self._online: set[str] = set()

    @property
    def connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    @property
    def servers(self) -> str | list[str]:
        return self._servers

    async def start(self) -> None:
        """Connect, publish our registry, seed state, and start watchers."""
        self._nc = await nats.connect(
            self._servers,
            name=f"castle-{self._local_hostname}",
            max_reconnect_attempts=-1,  # reconnect forever — nodes come and go
        )
        js = self._nc.jetstream()
        try:
            self._kv = await js.key_value(REGISTRY_BUCKET)
        except Exception:
            self._kv = await js.create_key_value(
                config=KeyValueConfig(bucket=REGISTRY_BUCKET, history=1)
            )

        await self.publish_registry(self._local_registry)
        await self._seed_existing()

        self._tasks = [
            asyncio.create_task(self._watch_loop()),
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._prune_loop()),
        ]
        logger.info("NATS mesh client started (servers=%s)", self._servers)

    async def stop(self) -> None:
        """Delete our key (immediate offline to peers) and disconnect."""
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []
        if self._kv is not None:
            with contextlib.suppress(Exception):
                await self._kv.delete(self._local_hostname)
        if self._nc is not None:
            with contextlib.suppress(Exception):
                await self._nc.drain()
            self._nc = None
        logger.info("NATS mesh client stopped")

    async def publish_registry(self, registry: NodeRegistry) -> None:
        """PUT (or refresh) our local registry into the KV bucket."""
        self._local_registry = registry
        if self._kv is None:
            return
        await self._kv.put(
            self._local_hostname, registry_to_json(registry).encode()
        )

    async def _seed_existing(self) -> None:
        """Load every peer key already present in the bucket."""
        if self._kv is None:
            return
        try:
            keys = await self._kv.keys()
        except Exception:
            keys = []  # empty bucket raises NoKeysError in nats-py
        for key in keys:
            if key == self._local_hostname:
                continue
            with contextlib.suppress(Exception):
                entry = await self._kv.get(key)
                if entry.value:
                    self._apply_put(key, entry.value.decode())

    async def _watch_loop(self) -> None:
        assert self._kv is not None
        watcher = await self._kv.watchall()
        async for entry in watcher:
            if entry is None:  # "caught up with current values" sentinel
                continue
            key = entry.key
            if key == self._local_hostname:
                continue
            try:
                if entry.operation in ("DEL", "PURGE"):
                    await self._apply_delete(key)
                elif entry.value:
                    changed = self._apply_put(key, entry.value.decode())
                    if changed:
                        await broadcast(
                            "mesh", {"event": "node_updated", "hostname": key}
                        )
            except Exception:
                logger.exception("Error handling mesh entry for %s", key)

    def _apply_put(self, hostname: str, payload: str) -> bool:
        """Update mesh state from a peer PUT. Returns True if content changed."""
        registry = json_to_registry(payload)
        mesh_state.update_node(hostname, registry)  # always refresh last-seen
        self._online.add(hostname)
        changed = self._last_json.get(hostname) != payload
        self._last_json[hostname] = payload
        return changed

    async def _apply_delete(self, hostname: str) -> None:
        mesh_state.set_offline(hostname)
        self._online.discard(hostname)
        self._last_json.pop(hostname, None)
        await broadcast("mesh", {"event": "node_offline", "hostname": hostname})

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SEC)
            with contextlib.suppress(Exception):
                await self.publish_registry(self._local_registry)

    async def _prune_loop(self) -> None:
        """Mark crashed peers (no refresh within the stale TTL) offline."""
        while True:
            await asyncio.sleep(PRUNE_SEC)
            all_nodes = mesh_state.all_nodes(include_stale=True)
            for host in list(self._online):
                node = all_nodes.get(host)
                if node is None or node.is_stale:
                    await self._apply_delete(host)
