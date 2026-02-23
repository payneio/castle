"""Mesh state manager — aggregates remote node registries."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from castle_core.registry import NodeRegistry

logger = logging.getLogger(__name__)

# Remote registries older than this are considered stale.
STALE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class RemoteNode:
    """A remote node's registry and metadata."""

    registry: NodeRegistry
    last_seen: float = field(default_factory=time.time)
    online: bool = True

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.last_seen) > STALE_TTL_SECONDS


class MeshStateManager:
    """Singleton holding remote node state discovered via MQTT.

    Thread-safe for reads from the FastAPI request handlers.
    Mutations happen only from the MQTT callback task.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, RemoteNode] = {}

    def update_node(self, hostname: str, registry: NodeRegistry) -> None:
        """Add or update a remote node's registry."""
        self._nodes[hostname] = RemoteNode(registry=registry)
        logger.info("Mesh: updated node %s (%d deployed)", hostname, len(registry.deployed))

    def set_offline(self, hostname: str) -> None:
        """Mark a node as offline (LWT received)."""
        if hostname in self._nodes:
            self._nodes[hostname].online = False
            logger.info("Mesh: node %s went offline", hostname)

    def remove_node(self, hostname: str) -> None:
        """Remove a node entirely."""
        if self._nodes.pop(hostname, None):
            logger.info("Mesh: removed node %s", hostname)

    def get_node(self, hostname: str) -> RemoteNode | None:
        """Get a specific remote node."""
        return self._nodes.get(hostname)

    def all_nodes(self, *, include_stale: bool = False) -> dict[str, RemoteNode]:
        """Return all remote nodes, optionally filtering out stale ones."""
        if include_stale:
            return dict(self._nodes)
        return {h: n for h, n in self._nodes.items() if not n.is_stale}

    def prune_stale(self) -> list[str]:
        """Remove nodes that have gone stale. Returns list of pruned hostnames."""
        pruned = [h for h, n in self._nodes.items() if n.is_stale]
        for h in pruned:
            del self._nodes[h]
            logger.info("Mesh: pruned stale node %s", h)
        return pruned


# Module-level singleton — imported by MQTT client and API routes.
mesh_state = MeshStateManager()
