"""Tests for the transport-agnostic mesh wire format (registry (de)serialization)."""

import json

from castle_core.registry import Deployment, NodeConfig, NodeRegistry

from castle_api.mesh_wire import json_to_registry, registry_to_json


def _make_registry() -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(
            hostname="tower", castle_root="/data/repos/castle", gateway_port=9000
        ),
        deployed={
            "my-svc": Deployment(
                manager="systemd",
                launcher="python",
                run_cmd=["uv", "run", "my-svc"],
                env={"PORT": "9001", "SECRET_KEY": "super-secret"},
                description="My service",
                name="my-svc",
                kind="service",
                stack="python-fastapi",
                port=9001,
                health_path="/health",
                subdomain="my-svc",
                managed=True,
            ),
            "my-job": Deployment(
                manager="systemd",
                launcher="command",
                run_cmd=["my-job"],
                name="my-job",
                kind="job",
                stack="python-cli",
                schedule="0 2 * * *",
            ),
        },
    )


class TestRegistrySerialization:
    """Round-trip serialization of NodeRegistry to/from JSON."""

    def test_round_trip(self) -> None:
        original = _make_registry()
        json_str = registry_to_json(original)
        restored = json_to_registry(json_str)

        assert restored.node.hostname == "tower"
        assert restored.node.gateway_port == 9000

    def test_deployed_components_preserved(self) -> None:
        original = _make_registry()
        restored = json_to_registry(registry_to_json(original))

        svc = restored.get("service", "my-svc")
        assert svc is not None
        assert svc.manager == "systemd"
        assert svc.launcher == "python"
        assert svc.port == 9001
        assert svc.health_path == "/health"
        assert svc.subdomain == "my-svc"
        assert svc.managed is True
        assert svc.kind == "service"
        assert svc.stack == "python-fastapi"

    def test_job_fields_preserved(self) -> None:
        original = _make_registry()
        restored = json_to_registry(registry_to_json(original))

        job = restored.get("job", "my-job")
        assert job is not None
        assert job.launcher == "command"
        assert job.schedule == "0 2 * * *"
        assert job.kind == "job"
        assert job.stack == "python-cli"

    def test_optional_fields_omitted(self) -> None:
        """Fields like port, health_path are None when not set."""
        reg = NodeRegistry(
            node=NodeConfig(hostname="minimal"),
            deployed={
                "bare": Deployment(
                    manager="systemd", launcher="command", run_cmd=["bare"], name="bare"
                ),
            },
        )
        restored = json_to_registry(registry_to_json(reg))
        bare = restored.get("service", "bare")
        assert bare.port is None
        assert bare.health_path is None
        assert bare.subdomain is None
        assert bare.schedule is None
        assert bare.managed is False

    def test_no_secrets_in_payload(self) -> None:
        """env vars, run_cmd, and castle_root must never appear on the wire."""
        original = _make_registry()
        json_str = registry_to_json(original)
        data = json.loads(json_str)

        # No castle_root in node
        assert "castle_root" not in data["node"]

        # No env or run_cmd in any component
        for name, comp in data["deployed"].items():
            assert "env" not in comp, f"{name} has env in payload"
            assert "run_cmd" not in comp, f"{name} has run_cmd in payload"
