"""Tests for castle gateway command."""

from __future__ import annotations

from pathlib import Path

from castle_cli.commands.gateway import _generate_caddyfile
from castle_cli.config import load_config


class TestCaddyfileGeneration:
    """Tests for Caddyfile generation."""

    def test_contains_gateway_port(self, castle_root: Path) -> None:
        """Caddyfile uses the configured gateway port."""
        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        assert ":18000 {" in caddyfile

    def test_contains_service_routes(self, castle_root: Path) -> None:
        """Caddyfile has reverse proxy routes for services with proxy.caddy."""
        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        assert "handle_path /test-svc/*" in caddyfile
        assert "reverse_proxy" in caddyfile
        assert "19000" in caddyfile

    def test_skips_tools(self, castle_root: Path) -> None:
        """Tools without proxy are not in Caddyfile."""
        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        assert "test-tool" not in caddyfile

    def test_fallback_when_no_dist(self, castle_root: Path) -> None:
        """Uses fallback dashboard path when dist/ doesn't exist."""
        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        # No dashboard/dist exists in tmp, so should use fallback
        assert "handle / {" in caddyfile
        assert "file_server" in caddyfile

    def test_spa_serving_when_dist_exists(self, castle_root: Path) -> None:
        """Serves SPA with try_files when dashboard/dist exists."""
        # Create a dashboard/dist with index.html
        dist = castle_root / "dashboard" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<html></html>")

        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        assert "try_files {path} /index.html" in caddyfile
        assert str(dist) in caddyfile

    def test_proxy_routes_before_dashboard(self, castle_root: Path) -> None:
        """Service proxy routes appear before the dashboard catch-all."""
        config = load_config(castle_root)
        caddyfile = _generate_caddyfile(config)
        proxy_pos = caddyfile.index("handle_path")
        handle_pos = caddyfile.index("handle /")
        assert proxy_pos < handle_pos
