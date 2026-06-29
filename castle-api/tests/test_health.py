"""Tests for castle-api health endpoint."""

from fastapi.testclient import TestClient


class TestHealth:
    """Health endpoint tests."""

    def test_health(self, client: TestClient) -> None:
        """Health endpoint returns ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestComponents:
    """Component list endpoint tests."""

    def test_list_components(self, client: TestClient) -> None:
        """Returns all registered components."""
        response = client.get("/deployments")
        assert response.status_code == 200
        data = response.json()
        names = [c["id"] for c in data]
        assert "test-svc" in names
        assert "test-tool" in names

    def test_service_has_port(self, client: TestClient) -> None:
        """Service component includes port info."""
        response = client.get("/deployments")
        data = response.json()
        svc = next(c for c in data if c["id"] == "test-svc")
        assert svc["port"] == 19000
        assert svc["health_path"] == "/health"
        assert svc["proxy_path"] == "/test-svc"
        assert svc["managed"] is True
        assert svc["behavior"] == "daemon"

    def test_tool_has_no_port(self, client: TestClient) -> None:
        """Tool component has no port."""
        response = client.get("/deployments")
        data = response.json()
        tool = next(c for c in data if c["id"] == "test-tool")
        assert tool["port"] is None
        assert tool["behavior"] == "tool"

    def test_job_has_schedule(self, client: TestClient) -> None:
        """Job component has schedule."""
        response = client.get("/deployments")
        data = response.json()
        job = next(c for c in data if c["id"] == "test-job")
        assert job["behavior"] == "tool"
        assert job["schedule"] == "0 2 * * *"


class TestDeploymentDetail:
    """Component detail endpoint tests."""

    def test_get_component(self, client: TestClient) -> None:
        """Returns detailed info for a component."""
        response = client.get("/deployments/test-svc")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-svc"
        assert "manifest" in data
        assert data["manifest"]["runner"] == "python"

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown component."""
        response = client.get("/deployments/nonexistent")
        assert response.status_code == 404


class TestServicesList:
    """GET /services endpoint tests."""

    def test_returns_deployed_services(self, client: TestClient) -> None:
        """Returns deployed services from registry."""
        response = client.get("/services")
        assert response.status_code == 200
        data = response.json()
        names = [s["id"] for s in data]
        assert "test-svc" in names

    def test_service_has_port_and_health(self, client: TestClient) -> None:
        """Service summary includes port and health info."""
        response = client.get("/services")
        data = response.json()
        svc = next(s for s in data if s["id"] == "test-svc")
        assert svc["port"] == 19000
        assert svc["health_path"] == "/health"
        assert svc["proxy_path"] == "/test-svc"
        assert svc["managed"] is True

    def test_no_schedule_field(self, client: TestClient) -> None:
        """ServiceSummary does not have schedule field."""
        response = client.get("/services")
        data = response.json()
        svc = next(s for s in data if s["id"] == "test-svc")
        assert "schedule" not in svc

    def test_no_installed_field(self, client: TestClient) -> None:
        """ServiceSummary does not have installed field."""
        response = client.get("/services")
        data = response.json()
        svc = next(s for s in data if s["id"] == "test-svc")
        assert "installed" not in svc

    def test_excludes_jobs(self, client: TestClient) -> None:
        """Jobs (scheduled items) are not in the services list."""
        response = client.get("/services")
        data = response.json()
        names = [s["id"] for s in data]
        assert "test-job" not in names


class TestServiceDetail:
    """GET /services/{name} endpoint tests."""

    def test_get_service(self, client: TestClient) -> None:
        """Returns detailed info for a service."""
        response = client.get("/services/test-svc")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-svc"
        assert "manifest" in data
        # manifest is the editable castle.yaml ServiceSpec (nested run spec)
        assert data["manifest"]["run"]["runner"] == "python"
        assert data["run_target"] == "test-svc"

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown service."""
        response = client.get("/services/nonexistent")
        assert response.status_code == 404


class TestJobsList:
    """GET /jobs endpoint tests."""

    def test_returns_jobs(self, client: TestClient) -> None:
        """Returns jobs from castle.yaml."""
        response = client.get("/jobs")
        assert response.status_code == 200
        data = response.json()
        names = [j["id"] for j in data]
        assert "test-job" in names

    def test_job_has_schedule(self, client: TestClient) -> None:
        """Job summary includes schedule."""
        response = client.get("/jobs")
        data = response.json()
        job = next(j for j in data if j["id"] == "test-job")
        assert job["schedule"] == "0 2 * * *"

    def test_no_port_field(self, client: TestClient) -> None:
        """JobSummary does not have port field."""
        response = client.get("/jobs")
        data = response.json()
        job = next(j for j in data if j["id"] == "test-job")
        assert "port" not in job

    def test_excludes_services(self, client: TestClient) -> None:
        """Services (non-scheduled) are not in the jobs list."""
        response = client.get("/jobs")
        data = response.json()
        names = [j["id"] for j in data]
        assert "test-svc" not in names


class TestJobDetail:
    """GET /jobs/{name} endpoint tests."""

    def test_get_job(self, client: TestClient) -> None:
        """Returns detailed info for a job."""
        response = client.get("/jobs/test-job")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-job"
        assert "manifest" in data
        assert data["schedule"] == "0 2 * * *"

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown job."""
        response = client.get("/jobs/nonexistent")
        assert response.status_code == 404


class TestProgramsList:
    """GET /programs endpoint tests."""

    def test_returns_programs(self, client: TestClient) -> None:
        """Returns programs from castle.yaml."""
        response = client.get("/programs")
        assert response.status_code == 200
        data = response.json()
        names = [p["id"] for p in data]
        assert "test-tool" in names

    def test_program_has_behavior(self, client: TestClient) -> None:
        """Program summary includes behavior."""
        response = client.get("/programs")
        data = response.json()
        tool = next(p for p in data if p["id"] == "test-tool")
        assert tool["behavior"] == "tool"

    def test_no_port_field(self, client: TestClient) -> None:
        """ProgramSummary does not have port field."""
        response = client.get("/programs")
        data = response.json()
        tool = next(p for p in data if p["id"] == "test-tool")
        assert "port" not in tool

    def test_no_schedule_field(self, client: TestClient) -> None:
        """ProgramSummary does not have schedule field."""
        response = client.get("/programs")
        data = response.json()
        tool = next(p for p in data if p["id"] == "test-tool")
        assert "schedule" not in tool


class TestProgramDetail:
    """GET /programs/{name} endpoint tests."""

    def test_get_program(self, client: TestClient) -> None:
        """Returns detailed info for a program."""
        response = client.get("/programs/test-tool")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "test-tool"
        assert "manifest" in data
        assert data["behavior"] == "tool"

    def test_not_found(self, client: TestClient) -> None:
        """Returns 404 for unknown program."""
        response = client.get("/programs/nonexistent")
        assert response.status_code == 404


class TestGateway:
    """Gateway info endpoint tests."""

    def test_gateway_info(self, client: TestClient) -> None:
        """Returns gateway configuration from registry."""
        response = client.get("/gateway")
        assert response.status_code == 200
        data = response.json()
        assert data["port"] == 9000
        assert data["hostname"] == "test-node"
        # Registry has 1 deployed component (test-svc)
        assert data["deployment_count"] == 1
        assert data["service_count"] == 1
        assert data["managed_count"] == 1

    def test_gateway_routes(self, client: TestClient) -> None:
        """Returns the full route table, tagged with kind + target."""
        response = client.get("/gateway")
        data = response.json()
        route = next(r for r in data["routes"] if r["address"] == "/test-svc")
        assert route["kind"] == "proxy"
        assert route["target"] == "localhost:19000"
        assert route["name"] == "test-svc"
        assert route["node"] == "test-node"

    def test_gateway_route_kinds_valid(self, client: TestClient) -> None:
        """Every route declares a known kind."""
        response = client.get("/gateway")
        data = response.json()
        assert data["routes"]
        for r in data["routes"]:
            assert r["kind"] in ("static", "proxy", "remote")

    def test_gateway_tls_off_by_default(self, client: TestClient) -> None:
        """No TLS configured → tls/ca_fingerprint are null (HTTP-only gateway)."""
        data = client.get("/gateway").json()
        assert data["tls"] is None
        assert data["ca_fingerprint"] is None

    def test_gateway_ca_404_without_internal_tls(self, client: TestClient) -> None:
        """The CA download is unavailable unless gateway.tls is 'internal'."""
        response = client.get("/gateway/ca.crt")
        assert response.status_code == 404


class TestConfigEditor:
    """Virtual castle.yaml aggregation/scatter endpoints."""

    def test_get_aggregates_resources(self, client: TestClient) -> None:
        """GET /config returns a unified YAML aggregating all resource files."""
        import yaml

        response = client.get("/config")
        assert response.status_code == 200
        data = yaml.safe_load(response.json()["yaml_content"])
        assert "test-tool" in data["programs"]
        assert "test-svc" in data["services"]
        assert "test-job" in data["jobs"]

    def test_put_scatters_and_prunes(self, client: TestClient, castle_root) -> None:
        """PUT /config writes resource files and prunes removed ones."""
        import yaml

        current = yaml.safe_load(client.get("/config").json()["yaml_content"])
        current["services"].pop("test-svc")
        current["programs"]["new-tool"] = {
            "description": "Brand new",
            "behavior": "tool",
        }
        resp = client.put("/config", json={"yaml_content": yaml.dump(current)})
        assert resp.status_code == 200, resp.text
        assert not (castle_root / "services" / "test-svc.yaml").exists()
        assert (castle_root / "programs" / "new-tool.yaml").exists()
        after = yaml.safe_load(client.get("/config").json()["yaml_content"])
        assert "new-tool" in after["programs"]
        assert "test-svc" not in (after.get("services") or {})
