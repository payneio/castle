"""Tests for Caddyfile generation — subdomain-only routing model."""

from __future__ import annotations

import pytest

from castle_core.config import CastleConfig, GatewayConfig
from castle_core.generators.caddyfile import (
    compute_routes,
    generate_caddyfile_from_registry,
)
from castle_core.manifest import (
    BuildSpec,
    ExposeSpec,
    HttpExposeSpec,
    HttpInternal,
    ProgramSpec,
    RunPython,
    RunStatic,
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
) -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(
            hostname="test",
            gateway_port=gateway_port,
            gateway_tls=gateway_tls,
            gateway_domain=gateway_domain,
            acme_email=acme_email,
        ),
        deployed=deployed or {},
    )


def _dep(port: int, *, expose: bool, name: str | None = None, runner: str = "python") -> Deployment:
    """A deployed service; exposed at <name>.<domain> when expose=True."""
    return Deployment(
        runner=runner, run_cmd=["x"], port=port, subdomain=(name if expose else None)
    )


def _acme(deployed: dict[str, Deployment], domain: str | None = "example.com") -> NodeRegistry:
    return _make_registry(
        gateway_tls="acme", gateway_domain=domain, acme_email="p@e.com", deployed=deployed
    )


class TestAcmeMode:
    """gateway.tls=acme → one *.domain wildcard site; every service is a subdomain."""

    def test_global_acme_block(self) -> None:
        cf = generate_caddyfile_from_registry(_acme({"api": _dep(9020, expose=True, name="api")}))
        assert "email p@e.com" in cf
        assert "acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}" in cf

    def test_service_is_a_subdomain_matcher(self) -> None:
        cf = generate_caddyfile_from_registry(
            _acme({"openclaw": _dep(18789, expose=True, name="openclaw")})
        )
        assert "*.example.com {" in cf
        # Subdomain is the service name.
        assert "@host_openclaw host openclaw.example.com" in cf
        assert "reverse_proxy localhost:18789" in cf

    def test_port_9000_redirects_to_dashboard(self) -> None:
        cf = generate_caddyfile_from_registry(_acme({"api": _dep(9020, expose=True, name="api")}))
        assert ":9000 {" in cf
        assert "redir https://castle.example.com{uri}" in cf

    def test_no_path_routes(self) -> None:
        cf = generate_caddyfile_from_registry(_acme({"api": _dep(9020, expose=True, name="api")}))
        assert "handle_path" not in cf
        assert "redir /" not in cf  # no path-prefix trailing-slash redirects
        assert "auto_https off" not in cf

    def test_unexposed_service_not_routed(self) -> None:
        cf = generate_caddyfile_from_registry(_acme({"pg": _dep(5432, expose=False, name="pg")}))
        assert "pg.example.com" not in cf

    def test_staging_toggle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CASTLE_ACME_STAGING", "1")
        cf = generate_caddyfile_from_registry(_acme({"api": _dep(9020, expose=True, name="api")}))
        assert "acme_ca https://acme-staging-v02.api.letsencrypt.org/directory" in cf

    def test_static_frontend_is_a_file_server_subdomain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A static frontend is a `runner: static` service serving <source>/<root>.
        import castle_core.config as config_mod

        cfg = _config(
            services={
                "castle": ServiceSpec(
                    program="castle", run=RunStatic(runner="static", root="dist")
                )
            },
            programs={"castle": ProgramSpec(source="/data/repos/castle/app")},
        )
        monkeypatch.setattr(config_mod, "load_config", lambda *a, **k: cfg)
        cf = generate_caddyfile_from_registry(_acme({}))
        assert "@host_castle host castle.example.com" in cf
        assert "root * /data/repos/castle/app/dist" in cf
        assert "try_files {path} /index.html" in cf
        assert "file_server" in cf


class TestOffMode:
    """No domain → HTTP-only control plane on :<port>: dashboard at / + /api → castle-api.
    Other services are port-only (not routed)."""

    def test_control_plane(self) -> None:
        cf = generate_caddyfile_from_registry(
            _make_registry(deployed={"castle-api": _dep(9020, expose=True, name="castle-api")})
        )
        assert "auto_https off" in cf
        assert "handle_path /api/* {" in cf
        assert "reverse_proxy localhost:9020" in cf
        assert "handle {" in cf  # dashboard catch-all (SPA fallback)

    def test_other_services_not_routed_in_off_mode(self) -> None:
        cf = generate_caddyfile_from_registry(
            _make_registry(deployed={"litellm": _dep(4000, expose=True, name="litellm")})
        )
        assert "litellm" not in cf  # no subdomains without a domain


def _service(port: int, *, expose: bool) -> ServiceSpec:
    return ServiceSpec(
        run=RunPython(runner="python", program="svc"),
        expose=ExposeSpec(http=HttpExposeSpec(internal=HttpInternal(port=port))),
        proxy=expose,
    )


def _config(
    services: dict[str, ServiceSpec], programs: dict[str, ProgramSpec] | None = None
) -> CastleConfig:
    return CastleConfig(
        root=None,  # type: ignore[arg-type]
        gateway=GatewayConfig(port=9000),
        repo=None,
        programs=programs or {},
        services=services,
        jobs={},
    )


class TestConfigSourceOfTruth:
    """compute_routes derives exposure/port from castle.yaml (the checkbox), so a
    regenerated Caddyfile tracks the spec, not a stale registry."""

    def test_exposed_service_becomes_a_route(self) -> None:
        routes = compute_routes(_make_registry(), _config({"claw": _service(18789, expose=True)}))
        r = next(r for r in routes if r.name == "claw")
        assert r.kind == "proxy"
        assert r.address == "claw"  # subdomain label = name
        assert r.target == "localhost:18789"

    def test_unexposed_service_has_no_route(self) -> None:
        routes = compute_routes(_make_registry(), _config({"pg": _service(5432, expose=False)}))
        assert not [r for r in routes if r.name == "pg"]

    def test_config_port_overrides_stale_registry(self) -> None:
        registry = _make_registry(
            deployed={"claw": _dep(8001, expose=True, name="claw")}
        )
        config = _config({"claw": _service(8002, expose=True)})
        routes = compute_routes(registry, config)
        assert {r.target for r in routes if r.name == "claw"} == {"localhost:8002"}

    def test_fallback_to_registry_without_config(self) -> None:
        # load_config is isolated (raises) → generate uses the registry snapshot.
        cf = generate_caddyfile_from_registry(
            _acme({"claw": _dep(8001, expose=True, name="claw")})
        )
        assert "@host_claw host claw.example.com" in cf
