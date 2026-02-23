"""SSH tunnel manager using paramiko."""

import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import paramiko

from .config import Config, HostConfig, TunnelConfig

logger = logging.getLogger(__name__)


class TunnelState(Enum):
    """State of a tunnel."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class TunnelStatus:
    """Status of a single tunnel."""

    config: TunnelConfig
    state: TunnelState = TunnelState.DISCONNECTED
    error: str | None = None
    connections: int = 0  # Active forwarded connections


@dataclass
class HostConnection:
    """Manages SSH connection and tunnels for a single host."""

    config: HostConfig
    tunnels: dict[str, TunnelStatus] = field(default_factory=dict)
    client: paramiko.SSHClient | None = None
    transport: paramiko.Transport | None = None
    _forward_threads: list[threading.Thread] = field(default_factory=list)
    _forward_servers: list[socket.socket] = field(default_factory=list)
    _stop_event: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        for tunnel in self.config.tunnels:
            self.tunnels[tunnel.name] = TunnelStatus(config=tunnel)


class TunnelManager:
    """Manages SSH tunnels based on configuration."""

    def __init__(
        self,
        config: Config,
        on_status_change: Callable[[str, str, TunnelState], None] | None = None,
    ):
        self.config = config
        self.on_status_change = on_status_change
        self.hosts: dict[str, HostConnection] = {}
        self._stop_event = threading.Event()
        self._reconnect_threads: list[threading.Thread] = []

        # Initialize host connections
        for host_config in config.hosts:
            key = f"{host_config.user}@{host_config.host}"
            self.hosts[key] = HostConnection(config=host_config)

    def start(self) -> None:
        """Start all tunnels."""
        self._stop_event.clear()
        for host_key, host_conn in self.hosts.items():
            self._connect_host(host_key, host_conn)

    def stop(self) -> None:
        """Stop all tunnels."""
        logger.info("Stopping all tunnels...")
        self._stop_event.set()

        for host_conn in self.hosts.values():
            self._disconnect_host(host_conn)

        # Wait for reconnect threads to finish
        for thread in self._reconnect_threads:
            thread.join(timeout=2)
        self._reconnect_threads.clear()

    def get_status(self) -> dict[str, dict[str, TunnelStatus]]:
        """Get status of all tunnels."""
        return {host_key: host.tunnels for host_key, host in self.hosts.items()}

    def _connect_host(self, host_key: str, host_conn: HostConnection) -> bool:
        """Connect to a host and establish all tunnels."""
        config = host_conn.config

        # Update all tunnel states to connecting
        for tunnel_status in host_conn.tunnels.values():
            self._update_state(host_key, tunnel_status, TunnelState.CONNECTING)

        try:
            # Create SSH client
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection kwargs
            connect_kwargs: dict = {
                "hostname": config.host,
                "port": config.port,
                "username": config.user,
            }

            # Add key file if specified
            if config.key_file:
                key_path = Path(config.key_file).expanduser()
                if not key_path.exists():
                    raise FileNotFoundError(f"SSH key file not found: {key_path}")
                connect_kwargs["key_filename"] = str(key_path)

            logger.info(f"Connecting to {config.user}@{config.host}:{config.port}...")
            client.connect(**connect_kwargs)

            host_conn.client = client
            host_conn.transport = client.get_transport()

            if host_conn.transport is None:
                raise ConnectionError("Failed to get transport")

            # Start port forwarding for each tunnel
            host_conn._stop_event.clear()
            for tunnel_config in config.tunnels:
                self._start_tunnel(host_key, host_conn, tunnel_config)

            logger.info(f"Connected to {config.host}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to {config.host}: {e}")
            for tunnel_status in host_conn.tunnels.values():
                tunnel_status.error = str(e)
                self._update_state(host_key, tunnel_status, TunnelState.ERROR)
            self._schedule_reconnect(host_key, host_conn)
            return False

    def _disconnect_host(self, host_conn: HostConnection) -> None:
        """Disconnect from a host."""
        host_conn._stop_event.set()

        # Close forward servers
        for server in host_conn._forward_servers:
            try:
                server.close()
            except Exception:
                pass
        host_conn._forward_servers.clear()

        # Wait for forward threads
        for thread in host_conn._forward_threads:
            thread.join(timeout=1)
        host_conn._forward_threads.clear()

        # Close SSH connection
        if host_conn.client:
            try:
                host_conn.client.close()
            except Exception:
                pass
            host_conn.client = None
            host_conn.transport = None

    def _start_tunnel(
        self, host_key: str, host_conn: HostConnection, tunnel_config: TunnelConfig
    ) -> None:
        """Start a single port forward tunnel."""
        tunnel_status = host_conn.tunnels[tunnel_config.name]

        try:
            # Create local listening socket
            local_port = tunnel_config.local_port or tunnel_config.remote_port
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", local_port))
            server.listen(5)
            server.settimeout(1.0)  # Allow checking stop event

            host_conn._forward_servers.append(server)

            # Start accept thread
            thread = threading.Thread(
                target=self._accept_loop,
                args=(host_key, host_conn, tunnel_config, server),
                daemon=True,
            )
            thread.start()
            host_conn._forward_threads.append(thread)

            self._update_state(host_key, tunnel_status, TunnelState.CONNECTED)
            logger.info(
                f"Tunnel '{tunnel_config.name}' open: "
                f"localhost:{local_port} -> {tunnel_config.remote_host}:{tunnel_config.remote_port}"
            )

        except Exception as e:
            logger.error(f"Failed to start tunnel '{tunnel_config.name}': {e}")
            tunnel_status.error = str(e)
            self._update_state(host_key, tunnel_status, TunnelState.ERROR)

    def _accept_loop(
        self,
        host_key: str,
        host_conn: HostConnection,
        tunnel_config: TunnelConfig,
        server: socket.socket,
    ) -> None:
        """Accept loop for forwarding connections."""
        tunnel_status = host_conn.tunnels[tunnel_config.name]

        while not host_conn._stop_event.is_set() and not self._stop_event.is_set():
            try:
                client_socket, addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # Socket was closed

            # Check if transport is still active
            if host_conn.transport is None or not host_conn.transport.is_active():
                client_socket.close()
                self._update_state(host_key, tunnel_status, TunnelState.ERROR)
                tunnel_status.error = "SSH connection lost"
                break

            # Open channel to remote
            try:
                channel = host_conn.transport.open_channel(
                    "direct-tcpip",
                    (tunnel_config.remote_host, tunnel_config.remote_port),
                    client_socket.getpeername(),
                )
            except Exception as e:
                logger.error(f"Failed to open channel for {tunnel_config.name}: {e}")
                client_socket.close()
                continue

            if channel is None:
                logger.error(f"Failed to open channel for {tunnel_config.name}")
                client_socket.close()
                continue

            # Start forwarding thread
            tunnel_status.connections += 1
            thread = threading.Thread(
                target=self._forward_data,
                args=(client_socket, channel, tunnel_status),
                daemon=True,
            )
            thread.start()

        # Connection lost, trigger reconnect
        if not self._stop_event.is_set():
            self._schedule_reconnect(host_key, host_conn)

    def _forward_data(
        self,
        client_socket: socket.socket,
        channel: paramiko.Channel,
        tunnel_status: TunnelStatus,
    ) -> None:
        """Forward data between client socket and SSH channel."""
        try:
            while True:
                # Check both directions for data
                r_ready = []

                # Use select for multiplexing
                import select

                try:
                    r_ready, _, _ = select.select([client_socket, channel], [], [], 1.0)
                except Exception:
                    break

                if client_socket in r_ready:
                    data = client_socket.recv(4096)
                    if not data:
                        break
                    channel.send(data)

                if channel in r_ready:
                    data = channel.recv(4096)
                    if not data:
                        break
                    client_socket.send(data)

        except Exception as e:
            logger.debug(f"Forward connection closed: {e}")
        finally:
            tunnel_status.connections -= 1
            try:
                client_socket.close()
            except Exception:
                pass
            try:
                channel.close()
            except Exception:
                pass

    def _schedule_reconnect(self, host_key: str, host_conn: HostConnection) -> None:
        """Schedule a reconnection attempt."""
        if self._stop_event.is_set():
            return

        thread = threading.Thread(
            target=self._reconnect_loop,
            args=(host_key, host_conn),
            daemon=True,
        )
        thread.start()
        self._reconnect_threads.append(thread)

    def _reconnect_loop(self, host_key: str, host_conn: HostConnection) -> None:
        """Reconnection loop with exponential backoff."""
        delay = self.config.reconnect_delay

        while not self._stop_event.is_set():
            logger.info(f"Reconnecting to {host_conn.config.host} in {delay}s...")

            # Wait with stop check
            for _ in range(delay):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

            # Disconnect first
            self._disconnect_host(host_conn)

            # Try to connect
            if self._connect_host(host_key, host_conn):
                return  # Success

            # Exponential backoff
            delay = min(delay * 2, self.config.max_reconnect_delay)

    def _update_state(self, host_key: str, tunnel_status: TunnelStatus, state: TunnelState) -> None:
        """Update tunnel state and notify callback."""
        tunnel_status.state = state
        if state != TunnelState.ERROR:
            tunnel_status.error = None

        if self.on_status_change:
            self.on_status_change(host_key, tunnel_status.config.name, state)
