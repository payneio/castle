"""Tests for Caddyfile generation from registry."""

from __future__ import annotations


import pytest

from castle_core.config import CastleConfig, GatewayConfig
from castle_core.generators.caddyfile import (
    compute_routes,
    generate_caddyfile_from_registry,
)
from castle_core.manifest import (
    CaddySpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ProxySpec,
    RunPython,
    ServiceSpec,
)
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
    gateway_tls: str | None = None,
    gateway_domain: str | None = None,
    acme_email: str | None = None,
    acme_dns_provider: str = "cloudflare",
) -> NodeRegistry:
    """Create a test registry."""
    return NodeRegistry(
        node=NodeConfig(
            hostname="test",
            gateway_port=gateway_port,
            gateway_tls=gateway_tls,
            gateway_domain=gateway_domain,
            acme_email=acme_email,
            acme_dns_provider=acme_dns_provider,
        ),
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

    def test_disables_auto_https(self) -> None:
        """The gateway is HTTP-only; auto_https must be off so named hosts don't
        flip the listener to TLS or try to bind :80."""
        caddyfile = generate_caddyfile_from_registry(_make_registry())
        assert "auto_https off" in caddyfile

    def test_host_route_uses_matcher_in_main_site(self) -> None:
        """A proxy_host becomes a host matcher inside the :9000 site (not a
        separate site block, which would split the listener into TLS)."""
        registry = _make_registry(
            deployed={
                "lake": Deployment(
                    runner="python",
                    run_cmd=["lake"],
                    port=8420,
                    proxy_host="lake.example.lan",
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "@host_lake host lake.example.lan" in caddyfile
        assert "handle @host_lake {" in caddyfile
        assert "reverse_proxy localhost:8420" in caddyfile
        # No separate hostname site block on the gateway port.
        assert "lake.example.lan:9000 {" not in caddyfile

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


def _service(port: int, path: str | None = None, host: str | None = None) -> ServiceSpec:
    """A minimal python ServiceSpec with an HTTP port and a caddy proxy route."""
    caddy = CaddySpec(path_prefix=path, host=host)
    return ServiceSpec(
        run=RunPython(runner="python", program="svc"),
        expose=ExposeSpec(http=HttpExposeSpec(internal=HttpInternal(port=port))),
        proxy=ProxySpec(caddy=caddy),
    )


def _config(services: dict[str, ServiceSpec]) -> CastleConfig:
    return CastleConfig(
        root=None,  # type: ignore[arg-type]
        gateway=GatewayConfig(port=9000),
        repo=None,
        programs={},
        services=services,
        jobs={},
    )


class TestLocalRoutesFromConfig:
    """castle.yaml is the source of truth for local routes — a regenerated
    Caddyfile must track the spec even when the deployed registry is stale.
    This is the regression guard for the service-edit drift."""

    def test_config_port_overrides_stale_registry(self) -> None:
        # Registry was deployed with the OLD port; castle.yaml now says 8002.
        registry = _make_registry(
            deployed={
                "app": Deployment(
                    runner="python", run_cmd=["app"], port=8001, proxy_path="/app"
                ),
            }
        )
        config = _config({"app": _service(port=8002, path="/app")})
        routes = compute_routes(registry, config)
        targets = {r.target for r in routes if r.address == "/app"}
        assert targets == {"localhost:8002"}  # config wins, not the stale 8001

    def test_config_path_overrides_stale_registry(self) -> None:
        registry = _make_registry(
            deployed={
                "app": Deployment(
                    runner="python", run_cmd=["app"], port=8001, proxy_path="/old"
                ),
            }
        )
        config = _config({"app": _service(port=8001, path="/new")})
        addrs = {r.address for r in compute_routes(registry, config) if r.kind == "proxy"}
        assert addrs == {"/new"}

    def test_falls_back_to_registry_without_config(self) -> None:
        # No config available (load_config is isolated to raise) → use registry.
        registry = _make_registry(
            deployed={
                "app": Deployment(
                    runner="python", run_cmd=["app"], port=8001, proxy_path="/app"
                ),
            }
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "reverse_proxy localhost:8001" in caddyfile


class TestCaddyfileOffMode:
    """gateway.tls unset/off → HTTP-only: host matchers live on the :<port> site."""

    def _host_registry(self) -> NodeRegistry:
        return _make_registry(
            deployed={
                "claw": Deployment(
                    runner="node", run_cmd=["claw"], port=18789, proxy_host="claw.civil.lan"
                ),
                "api": Deployment(
                    runner="python", run_cmd=["api"], port=9020, proxy_path="/api"
                ),
            },
        )

    def test_host_matcher_and_auto_https_off(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._host_registry())
        assert "auto_https off" in caddyfile
        assert "@host_claw host claw.civil.lan" in caddyfile
        assert "tls internal" not in caddyfile  # internal mode is gone
        assert "claw.civil.lan {" not in caddyfile  # not a standalone TLS site

    def test_path_routes_on_http_port(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._host_registry())
        assert ":9000 {" in caddyfile
        assert "handle_path /api/*" in caddyfile

    def test_routing_is_runner_agnostic(self) -> None:
        """A compose-runner service with a host route is matched like any other."""
        registry = _make_registry(
            deployed={
                "supabase": Deployment(
                    runner="compose",
                    run_cmd=["docker", "compose", "-p", "castle-supabase", "up"],
                    port=8000,
                    proxy_host="supabase.lan",
                ),
            },
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "@host_supabase host supabase.lan" in caddyfile
        assert "reverse_proxy localhost:8000" in caddyfile


class TestCaddyfileTlsAcme:
    """gateway.tls=acme → host routes served under one *.domain wildcard site
    with a Let's Encrypt cert via DNS-01."""

    def _acme_registry(self, domain: str | None = "civil.payne.io") -> NodeRegistry:
        return _make_registry(
            gateway_tls="acme",
            gateway_domain=domain,
            acme_email="paul@example.com",
            deployed={
                "claw": Deployment(
                    runner="node", run_cmd=["claw"], port=18789, proxy_host="claw.civil.lan"
                ),
                "api": Deployment(
                    runner="python", run_cmd=["api"], port=9020, proxy_path="/api"
                ),
            },
        )

    def test_global_email_and_acme_dns(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._acme_registry())
        assert "email paul@example.com" in caddyfile
        assert "acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}" in caddyfile

    def test_wildcard_site_with_derived_host_matcher(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._acme_registry())
        assert "*.civil.payne.io {" in caddyfile
        # Published name = the host's first label under the gateway domain.
        assert "@host_claw host claw.civil.payne.io" in caddyfile
        assert "reverse_proxy localhost:18789" in caddyfile

    def test_subdomain_from_host_label_not_service_name(self) -> None:
        # Service is named "openclaw" but declares host label "claw" → the label
        # wins (published as claw.<domain>), so the declared name is authoritative.
        registry = _make_registry(
            gateway_tls="acme",
            gateway_domain="civil.payne.io",
            acme_email="paul@example.com",
            deployed={
                "openclaw": Deployment(
                    runner="node", run_cmd=["c"], port=18789, proxy_host="claw"
                ),
            },
        )
        caddyfile = generate_caddyfile_from_registry(registry)
        assert "host claw.civil.payne.io" in caddyfile
        assert "openclaw.civil.payne.io" not in caddyfile

    def test_path_routes_stay_on_http_port(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._acme_registry())
        assert ":9000 {" in caddyfile
        assert "handle_path /api/*" in caddyfile

    def test_no_auto_https_off_and_no_internal_ca(self) -> None:
        caddyfile = generate_caddyfile_from_registry(self._acme_registry())
        assert "auto_https off" not in caddyfile
        assert "tls internal" not in caddyfile
        # The .lan host must not leak into the :9000 site as a plain matcher.
        assert "claw.civil.lan" not in caddyfile

    def test_staging_toggle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CASTLE_ACME_STAGING", "1")
        caddyfile = generate_caddyfile_from_registry(self._acme_registry())
        assert "acme_ca https://acme-staging-v02.api.letsencrypt.org/directory" in caddyfile

    def test_acme_without_domain_falls_back_to_http(self) -> None:
        # No domain → no *.None site; host route degrades to an off-mode matcher.
        caddyfile = generate_caddyfile_from_registry(self._acme_registry(domain=None))
        assert "*." not in caddyfile
        assert "auto_https off" in caddyfile
        assert "@host_claw host claw.civil.lan" in caddyfile


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
