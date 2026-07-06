"""castle tls — castle-managed TLS certs for raw-TCP services.

Each TLS-material TCP service (postgres, redis, …) gets the gateway's ACME
wildcard cert cut onto it so it presents a *trusted* cert on its raw port.
`reconcile` refreshes those copies from the wildcard and reloads the services
whose cert changed — it's what the Caddy `cert_obtained` hook and the nightly
safety-net job both run. `status` shows each service's cert fingerprint + expiry.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone

from castle_core.tls import _tls_of, reconcile_tls, tls_dir_for, wildcard_cert

from castle_cli.config import load_config


def run_tls(args: argparse.Namespace) -> int:
    if getattr(args, "tls_command", None) == "status":
        return _tls_status()
    return _tls_reconcile()


def _tls_reconcile() -> int:
    config = load_config()
    for msg in reconcile_tls(config):
        print(msg)
    return 0


def _fingerprint(pem: bytes) -> str:
    return hashlib.sha256(pem).hexdigest()[:12]


def _not_after(cert_pem: bytes) -> str:
    """Best-effort cert expiry (uses cryptography if available, else '—')."""
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(cert_pem)
        left = cert.not_valid_after_utc - datetime.now(timezone.utc)
        return f"{cert.not_valid_after_utc:%Y-%m-%d} ({left.days}d left)"
    except Exception:
        return "—"


def _tls_status() -> int:
    config = load_config()
    domain = config.gateway.domain
    src = wildcard_cert(domain) if domain else None
    src_fp = _fingerprint(src[0].read_bytes()) if src else None
    print(f"wildcard source: *.{domain} " + (f"[{src_fp}]" if src_fp else "(not found)"))

    rows = []
    for _kind, name, dep in config.all_deployments():
        if _tls_of(dep) is None:
            continue
        config_key = dep.program or name
        cert = tls_dir_for(config_key) / "cert.pem"
        combined = tls_dir_for(config_key) / "combined.pem"
        have = cert if cert.exists() else combined if combined.exists() else None
        if have is None:
            rows.append((name, "not materialized", "—", ""))
            continue
        pem = have.read_bytes()
        fp = _fingerprint(pem)
        drift = "" if src_fp and fp == src_fp else "  ⚠ stale (run: castle tls reconcile)"
        rows.append((name, fp, _not_after(pem), drift))

    if not rows:
        print("  (no TLS-material TCP services)")
        return 0
    print()
    for name, fp, exp, drift in rows:
        print(f"  {name:20s} {fp:14s} {exp}{drift}")
    return 0
