"""Tests for MQTT client serialization logic."""

import json

from castle_core.registry import DeployedComponent, NodeConfig, NodeRegistry

from castle_api.mqtt_client import _json_to_registry, _registry_to_json


def _make_registry() -> NodeRegistry:
    return NodeRegistry(
        node=NodeConfig(hostname="tower", castle_root="/data/repos/castle", gateway_port=9000),
        deployed={
            "my-svc": DeployedComponent(
                runner="python",
                run_cmd=["uv", "run", "my-svc"],
                env={"PORT": "9001", "SECRET_KEY": "super-secret"},
                description="My service",
                behavior="daemon",
                stack="python-fastapi",
                port=9001,
                health_path="/health",
                proxy_path="/my-svc",
                managed=True,
            ),
            "my-job": DeployedComponent(
                runner="command",
                run_cmd=["my-job"],
                behavior="tool",
                stack="python-cli",
                schedule="0 2 * * *",
            ),
        },
    )


class TestRegistrySerialization:
    """Round-trip serialization of NodeRegistry to/from JSON."""

    def test_round_trip(self) -> None:
        original = _make_registry()
        json_str = _registry_to_json(original)
        restored = _json_to_registry(json_str)

        assert restored.node.hostname == "tower"
        assert restored.node.gateway_port == 9000

    def test_deployed_components_preserved(self) -> None:
        original = _make_registry()
        restored = _json_to_registry(_registry_to_json(original))

        assert "my-svc" in restored.deployed
        svc = restored.deployed["my-svc"]
        assert svc.runner == "python"
        assert svc.port == 9001
        assert svc.health_path == "/health"
        assert svc.proxy_path == "/my-svc"
        assert svc.managed is True
        assert svc.behavior == "daemon"
        assert svc.stack == "python-fastapi"

    def test_job_fields_preserved(self) -> None:
        original = _make_registry()
        restored = _json_to_registry(_registry_to_json(original))

        assert "my-job" in restored.deployed
        job = restored.deployed["my-job"]
        assert job.runner == "command"
        assert job.schedule == "0 2 * * *"
        assert job.behavior == "tool"
        assert job.stack == "python-cli"

    def test_optional_fields_omitted(self) -> None:
        """Fields like port, health_path are None when not set."""
        reg = NodeRegistry(
            node=NodeConfig(hostname="minimal"),
            deployed={
                "bare": DeployedComponent(runner="command", run_cmd=["bare"]),
            },
        )
        restored = _json_to_registry(_registry_to_json(reg))
        bare = restored.deployed["bare"]
        assert bare.port is None
        assert bare.health_path is None
        assert bare.proxy_path is None
        assert bare.schedule is None
        assert bare.managed is False

    def test_no_secrets_in_payload(self) -> None:
        """env vars, run_cmd, and castle_root must not appear in MQTT payload."""
        original = _make_registry()
        json_str = _registry_to_json(original)
        data = json.loads(json_str)

        # No castle_root in node
        assert "castle_root" not in data["node"]

        # No env or run_cmd in any component
        for name, comp in data["deployed"].items():
            assert "env" not in comp, f"{name} has env in MQTT payload"
            assert "run_cmd" not in comp, f"{name} has run_cmd in MQTT payload"
