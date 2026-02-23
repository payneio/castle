"""Tests for Caddyfile generation from registry."""

from __future__ import annotations

from pathlib import Path

import pytest

import castle_core.generators.caddyfile as caddyfile_mod
from castle_core.generators.caddyfile import generate_caddyfile_from_registry
from castle_core.registry import DeployedComponent, NodeConfig, NodeRegistry


@pytest.fixture(autouse=True)
def _isolate_static_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a temp dir for STATIC_DIR so tests don't depend on real ~/.castle."""
    monkeypatch.setattr(caddyfile_mod, "STATIC_DIR", tmp_path / "static")


def _make_registry(
    deployed: dict[str, DeployedComponent] | None = None,
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
                "test-svc": DeployedComponent(
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
                "test-tool": DeployedComponent(
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
                "test-svc": DeployedComponent(
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
                "svc-a": DeployedComponent(
                    runner="python",
                    run_cmd=["uv", "run", "svc-a"],
                    port=9001,
                    proxy_path="/svc-a",
                ),
                "svc-b": DeployedComponent(
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
