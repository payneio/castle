"""MQTT client for inter-node mesh coordination.

Topics:
  castle/{hostname}/registry  — retained JSON NodeRegistry, published on connect
  castle/{hostname}/status    — "online" (retained) / "offline" (LWT)

On incoming messages from other hostnames, updates MeshStateManager.
"""

from __future__ import annotations

import asyncio
import json
import logging

import paho.mqtt.client as mqtt

from castle_core.registry import (
    DeployedComponent,
    NodeConfig,
    NodeRegistry,
)

from castle_api.mesh import mesh_state
from castle_api.stream import broadcast

logger = logging.getLogger(__name__)


def _registry_to_json(registry: NodeRegistry) -> str:
    """Serialize a NodeRegistry to JSON for MQTT publishing.

    Only includes fields needed for mesh routing — env vars, run_cmd,
    and castle_root are excluded to avoid leaking secrets.
    """
    data: dict = {
        "node": {
            "hostname": registry.node.hostname,
            "gateway_port": registry.node.gateway_port,
        },
        "deployed": {},
    }

    for name, comp in registry.deployed.items():
        entry: dict = {
            "runner": comp.runner,
            "category": comp.category,
        }
        if comp.description:
            entry["description"] = comp.description
        if comp.port is not None:
            entry["port"] = comp.port
        if comp.health_path:
            entry["health_path"] = comp.health_path
        if comp.proxy_path:
            entry["proxy_path"] = comp.proxy_path
        if comp.schedule:
            entry["schedule"] = comp.schedule
        if comp.managed:
            entry["managed"] = comp.managed
        data["deployed"][name] = entry

    return json.dumps(data)


def _json_to_registry(payload: str) -> NodeRegistry:
    """Deserialize a NodeRegistry from MQTT JSON payload."""
    data = json.loads(payload)
    node_data = data.get("node", {})
    node = NodeConfig(
        hostname=node_data.get("hostname", ""),
        castle_root=node_data.get("castle_root"),
        gateway_port=node_data.get("gateway_port", 9000),
    )
    deployed: dict[str, DeployedComponent] = {}
    for name, comp_data in data.get("deployed", {}).items():
        deployed[name] = DeployedComponent(
            runner=comp_data.get("runner", "command"),
            run_cmd=comp_data.get("run_cmd", []),
            env=comp_data.get("env", {}),
            description=comp_data.get("description"),
            category=comp_data.get("category", "service"),
            port=comp_data.get("port"),
            health_path=comp_data.get("health_path"),
            proxy_path=comp_data.get("proxy_path"),
            schedule=comp_data.get("schedule"),
            managed=comp_data.get("managed", False),
        )
    return NodeRegistry(node=node, deployed=deployed)


class CastleMQTTClient:
    """Async wrapper around paho-mqtt for castle mesh coordination."""

    def __init__(
        self,
        local_hostname: str,
        local_registry: NodeRegistry,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._local_hostname = local_hostname
        self._local_registry = local_registry
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._loop = loop or asyncio.get_event_loop()

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"castle-{local_hostname}",
            clean_session=True,
        )

        # LWT: if we disconnect unexpectedly, broker publishes "offline"
        self._client.will_set(
            f"castle/{local_hostname}/status",
            payload="offline",
            qos=1,
            retain=True,
        )

        self._connected = False
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_host(self) -> str:
        return self._broker_host

    @property
    def broker_port(self) -> int:
        return self._broker_port

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.DisconnectFlags,
        rc: mqtt.ReasonCode,
        properties: mqtt.Properties | None = None,
    ) -> None:
        self._connected = False
        logger.info("Disconnected from MQTT broker (rc=%s)", rc)

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: mqtt.ConnectFlags,
        rc: mqtt.ReasonCode,
        properties: mqtt.Properties | None = None,
    ) -> None:
        """Called when connected to broker — publish our state and subscribe."""
        if rc.is_failure:
            logger.error("MQTT connect failed: %s", rc)
            self._connected = False
            return

        self._connected = True
        logger.info("Connected to MQTT broker at %s:%d", self._broker_host, self._broker_port)

        # Publish our status as online (retained)
        client.publish(
            f"castle/{self._local_hostname}/status",
            payload="online",
            qos=1,
            retain=True,
        )

        # Publish our registry (retained)
        self.publish_registry(self._local_registry)

        # Subscribe to all castle nodes
        client.subscribe("castle/+/registry", qos=1)
        client.subscribe("castle/+/status", qos=1)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Process incoming MQTT messages from other nodes."""
        try:
            parts = msg.topic.split("/")
            if len(parts) != 3 or parts[0] != "castle":
                return

            hostname = parts[1]
            msg_type = parts[2]

            # Ignore our own messages
            if hostname == self._local_hostname:
                return

            payload = msg.payload.decode()

            if msg_type == "registry":
                registry = _json_to_registry(payload)
                mesh_state.update_node(hostname, registry)
                # Notify SSE clients about mesh change
                asyncio.run_coroutine_threadsafe(
                    broadcast("mesh", {"event": "node_updated", "hostname": hostname}),
                    self._loop,
                )

            elif msg_type == "status":
                if payload == "offline":
                    mesh_state.set_offline(hostname)
                    asyncio.run_coroutine_threadsafe(
                        broadcast("mesh", {"event": "node_offline", "hostname": hostname}),
                        self._loop,
                    )

        except Exception:
            logger.exception("Error processing MQTT message on %s", msg.topic)

    def publish_registry(self, registry: NodeRegistry) -> None:
        """Publish (or re-publish) our local registry."""
        self._local_registry = registry
        self._client.publish(
            f"castle/{self._local_hostname}/registry",
            payload=_registry_to_json(registry),
            qos=1,
            retain=True,
        )

    async def start(self) -> None:
        """Connect to the broker and start the network loop."""
        self._client.connect_async(self._broker_host, self._broker_port)
        self._client.loop_start()
        logger.info(
            "MQTT client starting (broker=%s:%d)",
            self._broker_host,
            self._broker_port,
        )

    async def stop(self) -> None:
        """Disconnect and stop the network loop."""
        # Publish offline status before disconnecting
        self._client.publish(
            f"castle/{self._local_hostname}/status",
            payload="offline",
            qos=1,
            retain=True,
        )
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT client stopped")
