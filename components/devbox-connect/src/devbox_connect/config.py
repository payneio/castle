"""Configuration loading and validation."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TunnelConfig:
    """Configuration for a single SSH tunnel."""

    name: str
    host: str
    remote_port: int
    local_port: int | None = None  # Defaults to remote_port if not specified
    user: str | None = None  # Defaults to global user
    key_file: str | None = None  # Defaults to global key_file
    remote_host: str = "localhost"  # The host on the remote side to connect to

    def __post_init__(self) -> None:
        if self.local_port is None:
            self.local_port = self.remote_port


@dataclass
class HostConfig:
    """Configuration for a host with multiple tunnels."""

    host: str
    user: str
    key_file: str | None = None
    port: int = 22
    tunnels: list[TunnelConfig] = field(default_factory=list)


@dataclass
class Config:
    """Root configuration."""

    hosts: list[HostConfig] = field(default_factory=list)
    reconnect_delay: int = 5  # Seconds between reconnection attempts
    max_reconnect_delay: int = 60  # Max delay with exponential backoff


class ConfigError(Exception):
    """Configuration error."""

    pass


def load_config(path: Path) -> Config:
    """Load configuration from a YAML file."""
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not data:
        raise ConfigError("Empty configuration file")

    return _parse_config(data)


def _parse_config(data: dict) -> Config:
    """Parse configuration dictionary into Config object."""
    config = Config(
        reconnect_delay=data.get("reconnect_delay", 5),
        max_reconnect_delay=data.get("max_reconnect_delay", 60),
    )

    # Handle simple format: list of tunnels with host info per tunnel
    if "tunnels" in data:
        config.hosts = _parse_simple_format(data["tunnels"], data)
    # Handle grouped format: hosts with nested tunnels
    elif "hosts" in data:
        config.hosts = _parse_grouped_format(data["hosts"])
    else:
        raise ConfigError("Config must contain either 'tunnels' or 'hosts' key")

    return config


def _parse_simple_format(tunnels: list[dict], global_config: dict) -> list[HostConfig]:
    """Parse simple format where each tunnel specifies its host."""
    # Group tunnels by host
    hosts_map: dict[str, HostConfig] = {}

    global_user = global_config.get("user")
    global_key_file = global_config.get("key_file")

    for t in tunnels:
        if "host" not in t:
            raise ConfigError(f"Tunnel '{t.get('name', 'unnamed')}' missing 'host'")
        if "remote_port" not in t:
            raise ConfigError(f"Tunnel '{t.get('name', 'unnamed')}' missing 'remote_port'")

        host = t["host"]
        user = t.get("user", global_user)
        if not user:
            raise ConfigError(f"Tunnel '{t.get('name', 'unnamed')}' missing 'user'")

        key_file = t.get("key_file", global_key_file)
        ssh_port = t.get("ssh_port", 22)

        # Create host key for grouping
        host_key = f"{user}@{host}:{ssh_port}"

        if host_key not in hosts_map:
            hosts_map[host_key] = HostConfig(
                host=host,
                user=user,
                key_file=key_file,
                port=ssh_port,
            )

        tunnel = TunnelConfig(
            name=t.get("name", f"{host}:{t['remote_port']}"),
            host=host,
            remote_port=t["remote_port"],
            local_port=t.get("local_port"),
            remote_host=t.get("remote_host", "localhost"),
        )
        hosts_map[host_key].tunnels.append(tunnel)

    return list(hosts_map.values())


def _parse_grouped_format(hosts: list[dict]) -> list[HostConfig]:
    """Parse grouped format with hosts containing nested tunnels."""
    result = []

    for h in hosts:
        if "host" not in h:
            raise ConfigError("Host entry missing 'host' field")
        if "user" not in h:
            raise ConfigError(f"Host '{h['host']}' missing 'user' field")

        host_config = HostConfig(
            host=h["host"],
            user=h["user"],
            key_file=h.get("key_file"),
            port=h.get("port", 22),
        )

        for t in h.get("tunnels", []):
            if "remote_port" not in t:
                raise ConfigError(f"Tunnel in host '{h['host']}' missing 'remote_port'")

            tunnel = TunnelConfig(
                name=t.get("name", f"{h['host']}:{t['remote_port']}"),
                host=h["host"],
                remote_port=t["remote_port"],
                local_port=t.get("local_port"),
                remote_host=t.get("remote_host", "localhost"),
            )
            host_config.tunnels.append(tunnel)

        result.append(host_config)

    return result
