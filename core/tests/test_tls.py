"""Tests for castle-managed TLS material (core/src/castle_core/tls.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

import castle_core.config as C
import castle_core.tls as T
from castle_core.manifest import SystemdDeployment


def _write_wildcard(xdg: Path, domain: str, tag: str, acme_dir: str) -> None:
    d = xdg / "caddy" / "certificates" / acme_dir / f"wildcard_.{domain}"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"wildcard_.{domain}.crt").write_bytes(f"CERT-{tag}\n".encode())
    (d / f"wildcard_.{domain}.key").write_bytes(f"KEY-{tag}\n".encode())


@pytest.fixture
def tls_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate Caddy's cert store (XDG_DATA_HOME, read live) and DATA_DIR (patched
    on the tls module) to a temp dir — no importlib.reload, so no global leak."""
    domain = "civil.payne.io"
    xdg = tmp_path / "xdg"
    _write_wildcard(xdg, domain, "PROD", "acme-v02.api.letsencrypt.org-directory")
    _write_wildcard(xdg, domain, "STAGING", "acme-staging-v02.api.letsencrypt.org-directory")
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setattr(T, "DATA_DIR", tmp_path / "data")  # tls_dir_for reads this
    return T, C, domain


def _cfg(C, domain, dep):
    return C.CastleConfig(
        root=None, gateway=C.GatewayConfig(port=9000, domain=domain), repo=None,
        programs={}, deployments={"postgres": dep},
    )


def _pg(material: str):
    return SystemdDeployment.model_validate(
        {
            "manager": "systemd",
            "program": "postgres",
            "run": {"launcher": "container", "image": "postgres:17"},
            "reach": "internal",
            "expose": {"tcp": {"port": 5432, "tls": {"material": material}}},
        }
    )


def test_prefers_prod_over_staging(tls_env) -> None:
    T, _, domain = tls_env
    crt, _ = T.wildcard_cert(domain)
    assert crt.read_text().strip() == "CERT-PROD"


def test_pair_material_and_idempotency(tls_env) -> None:
    T, C, domain = tls_env
    pg = _pg("pair")
    cfg = _cfg(C, domain, pg)
    assert T.materialize_tls(cfg, "postgres", pg) is True   # first write
    assert T.materialize_tls(cfg, "postgres", pg) is False  # idempotent
    td = T.tls_dir_for("postgres")
    assert sorted(p.name for p in td.iterdir()) == ["cert.pem", "chain.pem", "key.pem"]
    assert (td / "cert.pem").read_text().strip() == "CERT-PROD"
    assert oct((td / "key.pem").stat().st_mode)[-3:] == "600"   # secret
    assert oct((td / "cert.pem").stat().st_mode)[-3:] == "644"  # public


def test_material_switch_cleans_stale(tls_env) -> None:
    T, C, domain = tls_env
    pair = _pg("pair")
    T.materialize_tls(_cfg(C, domain, pair), "postgres", pair)
    combined = _pg("combined")
    assert T.materialize_tls(_cfg(C, domain, combined), "postgres", combined) is True
    td = T.tls_dir_for("postgres")
    assert sorted(p.name for p in td.iterdir()) == ["chain.pem", "combined.pem"]
    assert (td / "combined.pem").read_text() == "KEY-PROD\nCERT-PROD\n"  # key + cert
    assert oct((td / "combined.pem").stat().st_mode)[-3:] == "600"


def test_pair_chain_is_issuer_not_leaf(tls_env, tmp_path) -> None:
    """`chain.pem` (${tls_ca}) is the issuer chain — the intermediates only, leaf
    stripped — so it's a real CA bundle distinct from the leaf-bearing cert.pem
    (regression: they used to be byte-identical)."""
    T, C, domain = tls_env
    leaf = b"-----BEGIN CERTIFICATE-----\nLEAF\n-----END CERTIFICATE-----\n"
    inter = b"-----BEGIN CERTIFICATE-----\nINTERMEDIATE\n-----END CERTIFICATE-----\n"
    crt_dir = (
        Path(tmp_path) / "xdg" / "caddy" / "certificates"
        / "acme-v02.api.letsencrypt.org-directory" / f"wildcard_.{domain}"
    )
    (crt_dir / f"wildcard_.{domain}.crt").write_bytes(leaf + inter)
    pg = _pg("pair")
    assert T.materialize_tls(_cfg(C, domain, pg), "postgres", pg) is True
    td = T.tls_dir_for("postgres")
    assert (td / "cert.pem").read_bytes() == leaf + inter  # server presents leaf+chain
    assert (td / "chain.pem").read_bytes() == inter        # CA bundle = intermediates
    assert (td / "cert.pem").read_bytes() != (td / "chain.pem").read_bytes()


def test_material_off_is_noop(tls_env) -> None:
    T, C, domain = tls_env
    off = SystemdDeployment.model_validate(
        {"manager": "systemd", "program": "postgres",
         "run": {"launcher": "container", "image": "postgres:17"},
         "reach": "internal", "expose": {"tcp": {"port": 5432}}}
    )
    assert T.materialize_tls(_cfg(C, domain, off), "postgres", off) is False
    assert not T.tls_dir_for("postgres").exists()
