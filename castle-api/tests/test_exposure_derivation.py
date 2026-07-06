"""Exposure-derivation coverage for the gateway route table.

Guards the calculator bug: a public STATIC (caddy) deployment got public_url=None
because `public_names` scanned only config.services (systemd), not statics. Also
guards that a raw-TCP service is excluded from the HTTP route table (the
http_exposed derivation that decides subdomain/route).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from castle_api.main import app
from castle_core.registry import Deployment, NodeConfig, NodeRegistry, save_registry


@pytest.fixture
def public_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    root = tmp_path
    (root / "castle.yaml").write_text(
        yaml.dump(
            {
                "gateway": {
                    "port": 9000,
                    "tls": "acme",
                    "domain": "civil.test",
                    "public_domain": "pub.test",
                }
            }
        )
    )
    (root / "programs").mkdir()
    (root / "programs" / "calc.yaml").write_text(
        yaml.dump({"source": str(root / "calc")})
    )
    (root / "calc" / "public").mkdir(
        parents=True
    )  # static build dir must exist to route

    deps = {
        # public STATIC (the calculator case)
        "calc": {
            "program": "calc",
            "manager": "caddy",
            "root": "public",
            "reach": "public",
        },
        # public systemd service
        "web": {
            "manager": "systemd",
            "run": {"launcher": "python", "program": "web"},
            "expose": {"http": {"internal": {"port": 9001}}},
            "reach": "public",
        },
        # internal systemd service
        "intern": {
            "manager": "systemd",
            "run": {"launcher": "python", "program": "intern"},
            "expose": {"http": {"internal": {"port": 9002}}},
            "reach": "internal",
        },
        # raw-TCP service (postgres-like) — must NOT become an HTTP route
        "pg": {
            "manager": "systemd",
            "run": {"launcher": "container", "image": "postgres:17"},
            "expose": {"tcp": {"port": 5432}},
            "reach": "internal",
        },
    }
    (root / "deployments").mkdir()
    for name, spec in deps.items():
        (root / "deployments" / f"{name}.yaml").write_text(yaml.dump(spec))

    reg = NodeRegistry(
        node=NodeConfig(
            hostname="n",
            castle_root=str(root),
            gateway_port=9000,
            gateway_tls="acme",
            gateway_domain="civil.test",
            public_domain="pub.test",
        ),
        deployed={
            "calc": Deployment(
                manager="caddy",
                run_cmd=[],
                kind="static",
                subdomain="calc",
                public=True,
                static_root=str(root / "calc" / "public"),
            ),
            "web": Deployment(
                manager="systemd",
                launcher="python",
                run_cmd=["x"],
                kind="service",
                port=9001,
                subdomain="web",
                public=True,
                managed=True,
            ),
            "intern": Deployment(
                manager="systemd",
                launcher="python",
                run_cmd=["x"],
                kind="service",
                port=9002,
                subdomain="intern",
                public=False,
                managed=True,
            ),
            "pg": Deployment(
                manager="systemd",
                launcher="container",
                run_cmd=["x"],
                kind="service",
                port=None,
                subdomain=None,
                tcp_port=5432,
                managed=True,
            ),
        },
    )
    reg_path = tmp_path / "registry.yaml"
    save_registry(reg, reg_path)

    import castle_core.registry as reg_mod
    import castle_api.routes as routes_mod

    monkeypatch.setattr(reg_mod, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(
        routes_mod, "get_registry", lambda: reg_mod.load_registry(reg_path)
    )
    monkeypatch.setattr(routes_mod, "get_castle_root", lambda: root)

    with TestClient(app) as client:
        yield client


def _routes(client: TestClient) -> dict:
    return {r["name"]: r for r in client.get("/gateway").json()["routes"]}


class TestGatewayPublicUrl:
    def test_public_static_has_public_url(self, public_client: TestClient) -> None:
        """The calculator bug: a public STATIC must get public_url, not None."""
        assert _routes(public_client)["calc"]["public_url"] == "https://calc.pub.test"

    def test_public_service_has_public_url(self, public_client: TestClient) -> None:
        assert _routes(public_client)["web"]["public_url"] == "https://web.pub.test"

    def test_internal_service_has_no_public_url(
        self, public_client: TestClient
    ) -> None:
        assert _routes(public_client)["intern"]["public_url"] is None


class TestServiceDetailServesSpec:
    def test_services_endpoint_serves_static_editable_spec(
        self, public_client: TestClient
    ) -> None:
        """/services/{name} for a STATIC must serve the editable spec (reach/root/
        program), not the runtime view. This is the endpoint the dashboard's
        /services/ detail page reads — serving the runtime shape made the reach
        dropdown default to 'internal' for a public static (calculator)."""
        m = public_client.get("/services/calc").json()["manifest"]
        assert m.get("reach") == "public"  # <-- was None (runtime view) before the fix
        assert m.get("root") == "public"
        assert m.get("program") == "calc"


class TestDetailEndpointInvariant:
    """The invariant, swept across the matrix — not one example. Every deployment
    in castle.yaml must serve its EDITABLE SPEC (reach/program, no runtime-only
    keys) on EVERY detail endpoint the dashboard calls, for EVERY kind. Testing a
    single instance is what let the static x /services cell (calculator) rot."""

    @pytest.mark.parametrize(
        "endpoint,expected_reach",
        [
            ("/deployments/calc", "public"),  # static, unified endpoint
            ("/services/calc", "public"),  # static, /services endpoint (broke here)
            ("/deployments/web", "public"),  # service, unified endpoint
            ("/services/web", "public"),  # service, /services endpoint
            ("/deployments/intern", "internal"),
            ("/services/intern", "internal"),
        ],
    )
    def test_detail_serves_editable_spec(
        self, public_client: TestClient, endpoint: str, expected_reach: str
    ) -> None:
        m = public_client.get(endpoint).json()["manifest"]
        assert m.get("reach") == expected_reach  # spec field present
        assert "run_cmd" not in m  # not the runtime view

    @pytest.mark.parametrize("name", ["calc", "web", "intern"])
    def test_deployments_and_services_endpoints_agree(
        self, public_client: TestClient, name: str
    ) -> None:
        """The two detail endpoints must return the SAME editable manifest for the
        same deployment. Fixing one and forgetting its twin (the calculator bug)
        fails this immediately, whatever the kind."""
        dep = public_client.get(f"/deployments/{name}").json()["manifest"]
        svc = public_client.get(f"/services/{name}").json()["manifest"]
        assert dep.get("reach") == svc.get("reach")
        assert dep.get("program") == svc.get("program")
        assert dep.get("root") == svc.get("root")


class TestTcpNotHttpRouted:
    def test_tcp_service_absent_from_http_route_table(
        self, public_client: TestClient
    ) -> None:
        """A raw-TCP service (expose.tcp, no http) is reachable by name+port via
        DNS, never an HTTP gateway route — so it must not appear in the table."""
        assert "pg" not in _routes(public_client)
        # sanity: the HTTP services are present
        assert {"calc", "web", "intern"} <= set(_routes(public_client))
