"""Castle-managed TLS material for raw-TCP services.

Cuts the gateway's ACME wildcard cert (valid for ``<name>.<domain>``) onto a
service so it presents a *trusted* cert on its raw port, and refreshes it on
renewal. Protocol-agnostic: castle only copies files (in the requested format)
and signals the service — each deployment declares the format (``pair`` /
``combined``) and how it consumes the files (via the ``${tls_*}`` placeholders).

Two entry points:
- ``materialize_all`` — write/refresh the cert files, no reload (used by ``apply``,
  which (re)starts the service itself).
- ``reconcile_tls`` — materialize *and* reload the services whose cert changed
  (used by ``castle tls reconcile`` and the Caddy ``cert_obtained`` hook).
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from castle_core.config import CastleConfig
from castle_core.manifest import SystemdDeployment, TlsMaterial

_KEY_MODE_FILES = {"key.pem", "combined.pem"}  # secret → 0600; certs → 0644


def _caddy_data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "caddy"


def wildcard_cert(domain: str) -> tuple[Path, Path] | None:
    """``(crt, key)`` for ``*.<domain>`` from Caddy's store, or None.

    Caddy stores it at ``certificates/<acme-dir>/wildcard_.<domain>/…``. Prefer a
    production cert over staging (``CASTLE_ACME_STAGING=1`` yields a staging dir).
    The ``.crt`` is the full chain (leaf + intermediates).
    """
    store = _caddy_data_dir() / "certificates"
    if not store.is_dir():
        return None
    stem = f"wildcard_.{domain}"
    matches = sorted(
        store.glob(f"*/{stem}/{stem}.crt"),
        key=lambda p: 1 if "staging" in str(p) else 0,  # prod (0) before staging (1)
    )
    for crt in matches:
        key = crt.with_suffix(".key")
        if key.exists():
            return crt, key
    return None


def tls_dir_for(data_dir: Path, config_key: str) -> Path:
    """Where a deployment's materialized cert files live (``${tls_dir}``). `data_dir`
    is the instance root (config.data_dir) — the single source of truth."""
    return data_dir / config_key / "tls"


def _tls_of(dep: object) -> object | None:
    """The active TlsSpec for a deployment, or None (not systemd / no tcp / off)."""
    if not isinstance(dep, SystemdDeployment):
        return None
    tcp = dep.expose.tcp if dep.expose else None
    tls = tcp.tls if tcp else None
    if not tls or tls.material == TlsMaterial.OFF:
        return None
    return tls


_PEM_CERT = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\s*", re.DOTALL
)


def _issuer_chain(crt: bytes) -> bytes:
    """The issuer chain from a leaf+chain ``.crt``: every cert *after* the leaf
    (the intermediates), for ``${tls_ca}``. Empty when the ``.crt`` is a bare leaf
    (a genuine LE cert always ships an intermediate, so this is non-empty in
    practice)."""
    blocks = [m.group(0) for m in _PEM_CERT.finditer(crt)]
    return b"".join(blocks[1:])


def _wanted_files(
    tls_dir: Path, material: TlsMaterial, crt: bytes, key: bytes
) -> dict[Path, bytes]:
    """The exact file set for a material choice. ``chain.pem`` (for ``${tls_ca}``)
    is the *issuer chain* — the intermediates only, leaf stripped — so it's a real
    CA bundle distinct from the leaf-bearing ``cert.pem``/``combined.pem``, always
    provided regardless of material."""
    files: dict[Path, bytes] = {tls_dir / "chain.pem": _issuer_chain(crt)}
    if material == TlsMaterial.PAIR:
        files[tls_dir / "cert.pem"] = crt
        files[tls_dir / "key.pem"] = key
    elif material == TlsMaterial.COMBINED:
        files[tls_dir / "combined.pem"] = key + crt
    return files


def materialize_tls(config: CastleConfig, name: str, dep: object) -> bool:
    """Write ``dep``'s cert files from the wildcard, in its declared format.

    Idempotent: returns ``False`` (no write) when the on-disk copy already matches
    the source, so it's safe to call on every ``apply`` and every renewal event.
    Returns ``True`` when files were (re)written. No reload here — see callers.
    """
    tls = _tls_of(dep)
    if tls is None:
        return False
    domain = config.gateway.domain
    if not domain:
        return False
    src = wildcard_cert(domain)
    if src is None:
        return False
    crt_path, key_path = src
    crt, key = crt_path.read_bytes(), key_path.read_bytes()

    config_key = dep.program or name  # type: ignore[attr-defined]
    tls_dir = tls_dir_for(config.data_dir, config_key)
    wanted = _wanted_files(tls_dir, tls.material, crt, key)  # type: ignore[attr-defined]

    if all(p.exists() and p.read_bytes() == c for p, c in wanted.items()):
        return False  # already current

    tls_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tls_dir, 0o700)
    # Drop files left over from a previous material choice.
    for stale in ("cert.pem", "key.pem", "combined.pem", "chain.pem"):
        p = tls_dir / stale
        if p not in wanted and p.exists():
            p.unlink()
    for path, content in wanted.items():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.chmod(path, 0o600 if path.name in _KEY_MODE_FILES else 0o644)
    return True


def materialize_all(
    config: CastleConfig,
    messages: list[str] | None = None,
    only: list[str] | None = None,
) -> list[str]:
    """Materialize certs for TLS-material deployments; no reload. For ``apply``,
    which starts/restarts the services itself.

    ``only`` scopes materialization to the given deployment names (what a scoped
    ``castle apply <name>`` is converging). Left None → every deployment. Scoping
    keeps a scoped apply from rewriting an *unrelated* service's cert on disk
    without also reloading it (which would leave the file diverged from the running
    process until the next ``castle tls reconcile``)."""
    msgs = messages if messages is not None else []
    scope = set(only) if only is not None else None
    for _kind, name, dep in config.all_deployments():
        if scope is not None and name not in scope:
            continue
        if _tls_of(dep) is None:
            continue
        if materialize_tls(config, name, dep):
            msgs.append(f"tls: materialized cert for {name}")
    return msgs


def wait_for_wildcard(
    config: CastleConfig,
    names: list[str],
    messages: list[str] | None = None,
    timeout: float = 120.0,
    interval: float = 3.0,
) -> list[str]:
    """Block until the ACME wildcard cert exists, when an in-scope deployment needs
    castle-materialized TLS but the cert isn't issued yet.

    On a fresh node the gateway reload during ``apply`` only *kicks off* DNS-01
    issuance of ``*.<domain>`` (seconds to a couple minutes); materializing right
    after would find no cert and start the TLS service pointed at missing files —
    and with ``gateway.cert_hook`` disabled (the default) nothing would later
    reconcile it. Waiting here lets ``apply`` bring the service up with its cert in
    place on first deploy. Bounded: on timeout it warns and returns so ``apply``
    still proceeds (rerun ``castle tls reconcile`` once the cert lands)."""
    msgs = messages if messages is not None else []
    needs = [
        n
        for n in names
        if any(_tls_of(spec) is not None for _k, spec in config.deployments_named(n))
    ]
    if not needs:
        return msgs
    domain = config.gateway.domain
    if not domain or wildcard_cert(domain) is not None:
        return msgs  # no acme domain, or the cert already exists — nothing to wait on
    msgs.append(f"tls: waiting for ACME wildcard *.{domain} to be issued…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        if wildcard_cert(domain) is not None:
            msgs.append(f"tls: wildcard *.{domain} issued")
            return msgs
    msgs.append(
        f"tls: wildcard *.{domain} not ready after {int(timeout)}s — "
        f"{', '.join(needs)} may start without a cert; rerun `castle tls reconcile` "
        "once it is issued"
    )
    return msgs


def _reload(name: str, tls: object, msgs: list[str]) -> None:
    reload_cmd = getattr(tls, "reload", None)
    if reload_cmd:
        subprocess.run(reload_cmd, check=False)
        msgs.append(f"tls: reloaded {name} (reload command)")
    else:
        subprocess.run(
            ["systemctl", "--user", "restart", f"castle-{name}.service"], check=False
        )
        msgs.append(f"tls: restarted {name} to pick up rotated cert")


def reconcile_tls(config: CastleConfig, messages: list[str] | None = None) -> list[str]:
    """Materialize certs and reload the services whose cert changed. Idempotent —
    a no-op when nothing rotated. Invoked by ``castle tls reconcile`` and the Caddy
    ``cert_obtained`` hook. Logs its own outcome (the hook's ``exec`` swallows it)."""
    msgs = messages if messages is not None else []
    for _kind, name, dep in config.all_deployments():
        tls = _tls_of(dep)
        if tls is None:
            continue
        if materialize_tls(config, name, dep):
            msgs.append(f"tls: refreshed cert for {name}")
            _reload(name, tls, msgs)
    if not msgs:
        msgs.append("tls: all materialized certs current — nothing to do")
    return msgs
