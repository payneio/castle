"""Tests for the consumption audit (core/src/castle_core/audit.py)."""

from __future__ import annotations

import castle_core.config as C
from castle_core import audit
from castle_core.manifest import SystemdDeployment


def _svc(
    program: str,
    *,
    tcp: int | None = None,
    http: int | None = None,
    env: dict | None = None,
    requires: list | None = None,
) -> SystemdDeployment:
    spec: dict = {
        "manager": "systemd",
        "program": program,
        "run": {"launcher": "command", "argv": [program]},
    }
    if tcp is not None:
        spec["expose"] = {"tcp": {"port": tcp}}
        spec["reach"] = "internal"
    elif http is not None:
        spec["expose"] = {"http": {"internal": {"port": http}}}
        spec["reach"] = "internal"
    if env is not None:
        spec["defaults"] = {"env": env}
    if requires is not None:
        spec["requires"] = requires
    return SystemdDeployment.model_validate(spec)


def _cfg(deployments: dict) -> C.CastleConfig:
    return C.CastleConfig(
        root=None,
        gateway=C.GatewayConfig(port=9000),
        repo=None,
        programs={},
        deployments=deployments,
    )


def _pairs(cfg: C.CastleConfig) -> set[tuple[str, str]]:
    return {(s.consumer, s.provider) for s in audit.suggest_consumption(cfg)}


def test_split_host_port_pair_is_suggested() -> None:
    """A split X_HOST + X_PORT pair resolves like a single host:port value."""
    cfg = _cfg(
        {
            "broker": _svc("broker", tcp=1883),
            "api": _svc(
                "api",
                http=9020,
                env={"CASTLE_API_MQTT_HOST": "localhost", "CASTLE_API_MQTT_PORT": "1883"},
            ),
        }
    )
    assert ("api", "broker") in _pairs(cfg)


def test_single_value_url_is_suggested() -> None:
    cfg = _cfg(
        {
            "db": _svc("db", tcp=5432),
            "app": _svc("app", http=9001, env={"DATABASE_URL": "postgresql://u@localhost:5432/x"}),
        }
    )
    assert ("app", "db") in _pairs(cfg)


def test_bare_port_without_host_is_not_matched() -> None:
    """A deployment's own listen port (no host) must not become a dependency."""
    cfg = _cfg({"app": _svc("app", http=9001, env={"APP_PORT": "9001"})})
    assert _pairs(cfg) == set()


def test_declared_pair_is_not_suggested() -> None:
    """Already-declared consumption is not re-suggested."""
    cfg = _cfg(
        {
            "broker": _svc("broker", tcp=1883),
            "api": _svc(
                "api",
                http=9020,
                env={"X_HOST": "localhost", "X_PORT": "1883"},
                requires=[{"ref": "broker"}],
            ),
        }
    )
    assert ("api", "broker") not in _pairs(cfg)
