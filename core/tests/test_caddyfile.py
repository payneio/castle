"""Tests for Caddyfile generation from registry."""

from __future__ import annotations


import pytest

from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.registry import Deployment, NodeConfig, NodeRegistry


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the generator from the real ~/.castle config so static-frontend
    routes don't leak into these registry-focused tests."""
    import castle_core.config as config_mod

    def _no_config(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("isolated in tests")

    monkeypatch.setattr(config_mod, "load_config", _no_config)


def _make_registry(
    deployed: dict[str, Deployment] | None = None,
    gateway_port: int = 9000,
) -> NodeRegistry:
    """Create a test registry."""
    return NodeRegistry(
        node=NodeConfig(hostname="test", gateway_port=gateway_port),
        deployed=deployed or {},
    )


class TestCaddyfileFromRegistry:
    """Tests for registry-based Caddyfile generation."""

    def test_contains_gateway_port(self) -> None:
        """Caddyfile uses the configured gateway port."""
        registry = _make_registry(gateway_port=18000)
        caddyfile = generate_caddyfile_from_registry(registry)
        assert ":18000 {" in caddyfile

    def test_contains_service_routes(self) -> None:
        """Caddyfile has reverse proxy routes for deployed services."""
        registry = _make_registry(
            deployed={
                "test-svc": Deployment(
                    runner="python",
                    run_cmd=["uv", "run", "test-svc"],
                    port=19000,
                    proxy_path="/test-svc",
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "handle_path /test-svc/*" in caddyfile
        assert "reverse_proxy localhost:19000" in caddyfile

    def test_skips_non_proxied(self) -> None:
        """Components without proxy_path are not in Caddyfile."""
        registry = _make_registry(
            deployed={
                "test-tool": Deployment(
                    runner="command",
                    run_cmd=["test-tool"],
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "test-tool" not in caddyfile

    def test_fallback_when_no_static(self) -> None:
        """Uses fallback dashboard path when static dir doesn't exist."""
        registry = _make_registry()
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "handle / {" in caddyfile
        assert "file_server" in caddyfile

    def test_proxy_routes_before_dashboard(self) -> None:
        """Service proxy routes appear before the dashboard catch-all."""
        registry = _make_registry(
            deployed={
                "test-svc": Deployment(
                    runner="python",
                    run_cmd=["uv", "run", "test-svc"],
                    port=19000,
                    proxy_path="/test-svc",
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        proxy_pos = caddyfile.index("handle_path")
        handle_pos = caddyfile.index("handle /")
        assert proxy_pos < handle_pos

    def test_multiple_services(self) -> None:
        """Multiple services get separate proxy routes."""
        registry = _make_registry(
            deployed={
                "svc-a": Deployment(
                    runner="python",
                    run_cmd=["uv", "run", "svc-a"],
                    port=9001,
                    proxy_path="/svc-a",
                ),
                "svc-b": Deployment(
                    runner="python",
                    run_cmd=["uv", "run", "svc-b"],
                    port=9002,
                    proxy_path="/svc-b",
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "handle_path /svc-a/*" in caddyfile
        assert "reverse_proxy localhost:9001" in caddyfile
        assert "handle_path /svc-b/*" in caddyfile
        assert "reverse_proxy localhost:9002" in caddyfile


class TestCaddyfileRemoteRegistries:
    """Tests for cross-node routing in Caddyfile."""

    def test_remote_routes_included(self) -> None:
        """Remote services get reverse_proxy entries to their hostname."""
        local = _make_registry(
            deployed={
                "local-svc": Deployment(
                    runner="python", run_cmd=["svc"], port=9001, proxy_path="/local"
                ),
            }
        )
        remote = _make_registry(
            deployed={
                "remote-svc": Deployment(
                    runner="python", run_cmd=["svc"], port=9050, proxy_path="/remote"
                ),
            }
        )
        remote.node.hostname = "devbox"
        caddyfile = generate_caddyfile_from_registry(local, remote_registries={"devbox": remote})
        assert "reverse_proxy localhost:9001" in caddyfile
        assert "reverse_proxy devbox:9050" in caddyfile
        assert "handle_path /remote/*" in caddyfile

    def test_local_takes_precedence(self) -> None:
        """If local and remote use the same path, local wins."""
        local = _make_registry(
            deployed={
                "svc": Deployment(
                    runner="python", run_cmd=["svc"], port=9001, proxy_path="/api"
                ),
            }
        )
        remote = _make_registry(
            deployed={
                "svc": Deployment(
                    runner="python", run_cmd=["svc"], port=9001, proxy_path="/api"
                ),
            }
        )
        remote.node.hostname = "devbox"
        caddyfile = generate_caddyfile_from_registry(local, remote_registries={"devbox": remote})
        assert "reverse_proxy localhost:9001" in caddyfile
        assert "devbox" not in caddyfile

    def test_no_remote_when_none(self) -> None:
        """No remote routes when remote_registries is None."""
        local = _make_registry(
            deployed={
                "svc": Deployment(
                    runner="python", run_cmd=["svc"], port=9001, proxy_path="/api"
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(local, remote_registries=None)
        assert "reverse_proxy localhost:9001" in caddyfile
        # Only one reverse_proxy line
        assert caddyfile.count("reverse_proxy") == 1
