"""mDNS discovery for castle mesh — zero-config LAN peer and broker discovery.

Advertises this node as _castle._tcp and browses for:
  - _castle._tcp  — peer castle nodes
  - _mqtt._tcp    — MQTT broker address
"""

from __future__ import annotations

import logging
import socket

from zeroconf import ServiceBrowser, ServiceInfo, ServiceStateChange, Zeroconf

logger = logging.getLogger(__name__)

CASTLE_SERVICE_TYPE = "_castle._tcp.local."
MQTT_SERVICE_TYPE = "_mqtt._tcp.local."


class CastleMDNS:
    """Advertise this castle node and discover peers + MQTT broker via mDNS."""

    def __init__(
        self,
        hostname: str,
        gateway_port: int,
        api_port: int,
    ) -> None:
        self._hostname = hostname
        self._gateway_port = gateway_port
        self._api_port = api_port
        self._zeroconf: Zeroconf | None = None
        self._browsers: list[ServiceBrowser] = []
        self._service_info: ServiceInfo | None = None

        # Discovered state
        self.peers: dict[str, dict] = {}  # hostname -> {gateway_port, api_port, addresses}
        self.mqtt_broker: dict | None = None  # {host, port} or None

    def _on_service_state_change(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle discovered/removed services."""
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            info = zeroconf.get_service_info(service_type, name)
            if info is None:
                return

            if service_type == CASTLE_SERVICE_TYPE:
                self._handle_castle_peer(info)
            elif service_type == MQTT_SERVICE_TYPE:
                self._handle_mqtt_broker(info)

        elif state_change == ServiceStateChange.Removed:
            if service_type == CASTLE_SERVICE_TYPE:
                # Extract hostname from service name (format: "hostname._castle._tcp.local.")
                peer_hostname = name.replace(f".{CASTLE_SERVICE_TYPE}", "")
                if peer_hostname != self._hostname and peer_hostname in self.peers:
                    del self.peers[peer_hostname]
                    logger.info("mDNS: peer %s removed", peer_hostname)

    def _handle_castle_peer(self, info: ServiceInfo) -> None:
        """Process a discovered castle peer."""
        props = {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in info.properties.items()
        }
        peer_hostname = props.get("hostname", "")
        if not peer_hostname or peer_hostname == self._hostname:
            return

        addresses = [socket.inet_ntoa(addr) for addr in info.addresses if len(addr) == 4]

        self.peers[peer_hostname] = {
            "gateway_port": int(props.get("gateway_port", 9000)),
            "api_port": int(props.get("api_port", 9020)),
            "addresses": addresses,
        }
        logger.info("mDNS: discovered peer %s at %s", peer_hostname, addresses)

    def _handle_mqtt_broker(self, info: ServiceInfo) -> None:
        """Process a discovered MQTT broker."""
        addresses = [socket.inet_ntoa(addr) for addr in info.addresses if len(addr) == 4]
        if addresses:
            self.mqtt_broker = {
                "host": addresses[0],
                "port": info.port,
            }
            logger.info("mDNS: discovered MQTT broker at %s:%d", addresses[0], info.port)

    def start(self) -> None:
        """Start advertising and browsing."""
        self._zeroconf = Zeroconf()

        # Advertise ourselves
        self._service_info = ServiceInfo(
            CASTLE_SERVICE_TYPE,
            f"{self._hostname}.{CASTLE_SERVICE_TYPE}",
            port=self._gateway_port,
            properties={
                "hostname": self._hostname,
                "gateway_port": str(self._gateway_port),
                "api_port": str(self._api_port),
            },
        )
        self._zeroconf.register_service(self._service_info)
        logger.info("mDNS: advertising %s on port %d", self._hostname, self._gateway_port)

        # Browse for peers and MQTT broker
        self._browsers.append(
            ServiceBrowser(self._zeroconf, CASTLE_SERVICE_TYPE, handlers=[self._on_service_state_change])
        )
        self._browsers.append(
            ServiceBrowser(self._zeroconf, MQTT_SERVICE_TYPE, handlers=[self._on_service_state_change])
        )

    def stop(self) -> None:
        """Stop advertising and close."""
        if self._zeroconf:
            if self._service_info:
                self._zeroconf.unregister_service(self._service_info)
            self._zeroconf.close()
            self._zeroconf = None
        self._browsers.clear()
        logger.info("mDNS: stopped")
