"""Tests for castle configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from castle_core.config import (
    CastleConfig,
    load_config,
    resolve_env_split,
    resolve_env_vars,
    save_config,
)
from castle_core.manifest import ProgramSpec, SystemdDeployment


class TestLoadConfig:
    """Tests for loading castle.yaml."""

    def test_load_basic(self, castle_root: Path) -> None:
        """Load a castle.yaml with three sections."""
        config = load_config(castle_root)
        assert isinstance(config, CastleConfig)
        assert config.gateway.port == 18000
        assert "test-tool" in config.programs
        assert "test-svc" in config.services
        assert "test-job" in config.jobs

    def test_load_produces_typed_specs(self, castle_root: Path) -> None:
        """Each section produces the correct spec type."""
        config = load_config(castle_root)
        assert isinstance(config.programs["test-tool"], ProgramSpec)
        # Both a service and a job are systemd deployments; the kind (service/job)
        # is derived from whether a schedule is present.
        assert isinstance(config.services["test-svc"], SystemdDeployment)
        assert isinstance(config.jobs["test-job"], SystemdDeployment)

    def test_service_expose(self, castle_root: Path) -> None:
        """Service has correct expose spec."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.expose.http.internal.port == 19000
        assert svc.expose.http.health_path == "/health"

    def test_service_proxy(self, castle_root: Path) -> None:
        """Service has correct proxy spec."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.proxy is True  # exposed at <name>.<gateway.domain>

    def test_service_run_spec(self, castle_root: Path) -> None:
        """Service has correct launch spec (legacy runner normalized to launcher)."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.run.launcher == "python"
        assert svc.run.program == "test-svc"

    def test_service_component_ref(self, castle_root: Path) -> None:
        """Service references a component."""
        config = load_config(castle_root)
        svc = config.services["test-svc"]
        assert svc.program == "test-svc-comp"

    def test_job_schedule(self, castle_root: Path) -> None:
        """Job has correct schedule."""
        config = load_config(castle_root)
        job = config.jobs["test-job"]
        assert job.schedule == "0 2 * * *"

    def test_tools_property(self, castle_root: Path) -> None:
        """Tools property filters to components with install.path or tool."""
        config = load_config(castle_root)
        assert "test-tool" in config.tools

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        """Missing castle.yaml raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path)


class TestSaveConfig:
    """Tests for saving castle.yaml."""

    def test_round_trip(self, castle_root: Path) -> None:
        """Load and save should produce equivalent config."""
        config = load_config(castle_root)
        save_config(config)
        config2 = load_config(castle_root)

        assert config2.gateway.port == config.gateway.port
        assert set(config2.programs.keys()) == set(config.programs.keys())
        assert set(config2.services.keys()) == set(config.services.keys())
        assert set(config2.jobs.keys()) == set(config.jobs.keys())

    def test_save_adds_component(self, castle_root: Path) -> None:
        """Adding a component and saving persists it."""
        config = load_config(castle_root)
        config.programs["new-lib"] = ProgramSpec(
            id="new-lib", description="A new library"
        )
        save_config(config)

        config2 = load_config(castle_root)
        assert "new-lib" in config2.programs
        assert config2.programs["new-lib"].description == "A new library"

    def test_preserves_manage_systemd(self, castle_root: Path) -> None:
        """Roundtrip preserves manage.systemd even with all defaults."""
        config = load_config(castle_root)
        save_config(config)
        config2 = load_config(castle_root)
        svc = config2.services["test-svc"]
        assert svc.manage is not None
        assert svc.manage.systemd is not None

    def test_writes_directory_layout(self, castle_root: Path) -> None:
        """Save writes one file per resource under programs/ and one deployments/ dir."""
        config = load_config(castle_root)
        save_config(config)
        assert (castle_root / "programs" / "test-tool.yaml").exists()
        # Deployments live under per-kind subdirs (deployments/<store>/<name>.yaml).
        assert (castle_root / "deployments" / "services" / "test-svc.yaml").exists()
        assert (castle_root / "deployments" / "jobs" / "test-job.yaml").exists()
        assert (castle_root / "deployments" / "tools" / "test-tool.yaml").exists()
        # Global file holds gateway only, no resource sections
        global_data = yaml.safe_load((castle_root / "castle.yaml").read_text())
        assert global_data["gateway"]["port"] == 18000
        assert "programs" not in global_data
        assert "deployments" not in global_data

    def test_delete_prunes_file(self, castle_root: Path) -> None:
        """Removing a deployment and saving deletes its on-disk file."""
        config = load_config(castle_root)
        del config.services["test-svc"]
        save_config(config)
        assert not (castle_root / "deployments" / "services" / "test-svc.yaml").exists()
        config2 = load_config(castle_root)
        assert "test-svc" not in config2.services
        assert "test-tool" in config2.programs


class TestResolveEnvVars:
    """Tests for environment variable resolution."""

    def test_no_vars(self) -> None:
        """Plain values pass through unchanged."""
        env = {"MY_VAR": "plain_value"}
        resolved = resolve_env_vars(env)
        assert resolved["MY_VAR"] == "plain_value"

    def test_unrecognized_vars_preserved(self) -> None:
        """Non-secret ${} references pass through unchanged."""
        env = {"MY_VAR": "${unknown_var}"}
        resolved = resolve_env_vars(env)
        assert resolved["MY_VAR"] == "${unknown_var}"

    def test_resolve_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """${secret:NAME} resolves from secrets directory."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "API_KEY").write_text("my-secret-key\n")
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        env = {"API_KEY": "${secret:API_KEY}"}
        resolved = resolve_env_vars(env)
        assert resolved["API_KEY"] == "my-secret-key"

    def test_resolve_missing_secret(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing secret returns placeholder."""
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

        env = {"API_KEY": "${secret:NONEXISTENT}"}
        resolved = resolve_env_vars(env)
        assert resolved["API_KEY"] == "<MISSING_SECRET:NONEXISTENT>"


class TestResolveEnvSplit:
    """Tests for the secret/plain partition used to keep secrets out of units."""

    def _secrets(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **vals: str):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        for name, val in vals.items():
            (secrets_dir / name).write_text(val + "\n")
        monkeypatch.setattr("castle_core.config.SECRETS_DIR", secrets_dir)

    def test_plain_only(self) -> None:
        plain, secret = resolve_env_split({"PORT": "9001", "URL": "http://x"})
        assert plain == {"PORT": "9001", "URL": "http://x"}
        assert secret == {}

    def test_context_placeholders_are_plain(self) -> None:
        plain, secret = resolve_env_split(
            {"P": "${port}", "D": "${data_dir}"}, {"port": "9001", "data_dir": "/d"}
        )
        assert plain == {"P": "9001", "D": "/d"}
        assert secret == {}

    def test_pure_secret_partitioned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._secrets(tmp_path, monkeypatch, API_KEY="sk-123")
        plain, secret = resolve_env_split({"API_KEY": "${secret:API_KEY}"})
        assert plain == {}
        assert secret == {"API_KEY": "sk-123"}

    def test_composite_secret_partitioned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A value embedding a secret is secret-bearing; the whole value resolves."""
        self._secrets(tmp_path, monkeypatch, NEO4J_PASSWORD="pw")
        plain, secret = resolve_env_split(
            {"NEO4J_AUTH": "neo4j/${secret:NEO4J_PASSWORD}"}
        )
        assert plain == {}
        assert secret == {"NEO4J_AUTH": "neo4j/pw"}

    def test_mixed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._secrets(tmp_path, monkeypatch, K="v")
        plain, secret = resolve_env_split(
            {"PORT": "${port}", "K": "${secret:K}"}, {"port": "9001"}
        )
        assert plain == {"PORT": "9001"}
        assert secret == {"K": "v"}

    def test_missing_secret_still_partitioned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._secrets(tmp_path, monkeypatch)
        plain, secret = resolve_env_split({"K": "${secret:NOPE}"})
        assert plain == {}
        assert secret == {"K": "<MISSING_SECRET:NOPE>"}

    def test_resolve_env_vars_matches_merged_split(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The flat wrapper equals the merged split and preserves key order."""
        self._secrets(tmp_path, monkeypatch, K="v")
        env = {"PORT": "${port}", "K": "${secret:K}", "Z": "lit"}
        flat = resolve_env_vars(env, {"port": "9001"})
        assert flat == {"PORT": "9001", "K": "v", "Z": "lit"}
        assert list(flat.keys()) == ["PORT", "K", "Z"]


class TestConfigRoundTrip:
    """save_config → load_config must preserve every field. A field missing from
    the save path (the `cert_hook` regression) or the serializer silently drops on
    the next write — these lock the full round-trip for the reach/TCP-TLS fields."""

    def test_gateway_and_tcp_tls_survive_save_load(self, tmp_path: Path) -> None:
        from castle_core.config import GatewayConfig
        from castle_core.manifest import (
            ExposeSpec,
            Reach,
            RunContainer,
            SystemdDeployment,
            TcpExposeSpec,
            TlsMaterial,
            TlsSpec,
        )

        pg = SystemdDeployment(
            id="pg",
            manager="systemd",
            program="pg",
            reach=Reach.INTERNAL,
            run=RunContainer(
                launcher="container",
                image="postgres:17",
                user="${uid}:${gid}",
                tmpfs=["/var/run/postgresql"],
            ),
            expose=ExposeSpec(
                tcp=TcpExposeSpec(port=5432, tls=TlsSpec(material=TlsMaterial.PAIR))
            ),
        )
        config = CastleConfig(
            root=tmp_path,
            gateway=GatewayConfig(
                port=9000, tls="acme", domain="civil.payne.io", cert_hook=True
            ),
            repo=None,
            programs={},
            deployments={"pg": pg},
        )
        save_config(config)
        loaded = load_config(tmp_path)

        # Gateway: cert_hook must survive (the field that got dropped in prod).
        assert loaded.gateway.cert_hook is True
        assert loaded.gateway.tls == "acme"
        assert loaded.gateway.domain == "civil.payne.io"

        # Deployment: reach + full TCP/TLS + container user/tmpfs must survive.
        d = loaded.services["pg"]
        assert d.reach == Reach.INTERNAL
        assert d.expose.tcp.port == 5432
        assert d.expose.tcp.tls.material == TlsMaterial.PAIR
        assert d.run.user == "${uid}:${gid}"
        assert d.run.tmpfs == ["/var/run/postgresql"]

    def test_parse_gateway_preserves_all_fields(self) -> None:
        """The shared gateway parser must honor every field — `save_yaml` used to
        read only `port`, wiping tls/domain/tunnel/cert_hook on a whole-file save."""
        from castle_core.config import parse_gateway

        g = parse_gateway(
            {
                "port": 9000,
                "tls": "acme",
                "domain": "civil.payne.io",
                "acme_email": "a@b.co",
                "public_domain": "pub.io",
                "tunnel_id": "uuid-123",
                "cert_hook": True,
            }
        )
        assert g.tls == "acme"
        assert g.domain == "civil.payne.io"
        assert g.acme_email == "a@b.co"
        assert g.public_domain == "pub.io"
        assert g.tunnel_id == "uuid-123"
        assert g.cert_hook is True
