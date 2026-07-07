"""Pluggable secret backends for ``${secret:NAME}`` resolution.

Default is the **file** backend (``~/.castle/secrets/<name>``) — identical to the
historical behavior, so nothing changes unless a backend is explicitly selected
via ``CASTLE_SECRET_BACKEND``.

The **openbao** backend reads from an OpenBao/Vault KV-v2 mount and falls back to
the file backend, which is also how it bootstraps: the OpenBao *token* itself is a
file secret (it can't live in the vault it unlocks).

Selection (env, so it works in both the CLI and the systemd-run API):
  CASTLE_SECRET_BACKEND        file | openbao        (default: file)
  CASTLE_OPENBAO_ADDR          http://localhost:8200
  CASTLE_OPENBAO_MOUNT         castle                (kv-v2 mount path)
  CASTLE_OPENBAO_TOKEN_SECRET  OPENBAO_TOKEN         (file secret holding the token)
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Protocol


class SecretBackend(Protocol):
    def read(self, name: str) -> str | None: ...
    def write(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...
    def list_names(self) -> list[str]: ...


class FileSecretBackend:
    """Reads/writes ``<secrets_dir>/<name>`` (the historical behavior)."""

    def __init__(self, secrets_dir: Path) -> None:
        self._dir = secrets_dir

    def read(self, name: str) -> str | None:
        path = self._dir / name
        if path.exists():
            return path.read_text().strip()
        return None

    def write(self, name: str, value: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / name).write_text(value.strip() + "\n")

    def delete(self, name: str) -> None:
        path = self._dir / name
        if path.exists():
            path.unlink()

    def list_names(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(f.name for f in self._dir.iterdir() if f.is_file())


class OpenBaoBackend:
    """Reads/writes an OpenBao/Vault KV-v2 mount. No file fallback — a missing key
    or unreachable server returns None (the bootstrap token is read separately by
    ``build_backend`` via the file backend, not through here).

    ``node_prefix`` supports a shared vault with per-node overrides: a read tries
    ``<node_prefix>/<name>`` first, then the shared ``<name>``. So a node-specific
    secret (e.g. that node's postgres password) lives at the prefixed path while
    shared secrets (a common token) live at the base — no name collision.
    """

    def __init__(
        self, addr: str, token: str, mount: str, node_prefix: str | None = None
    ) -> None:
        self._addr = addr.rstrip("/")
        self._token = token
        self._mount = mount
        self._node_prefix = (node_prefix or "").strip("/")

    def read(self, name: str) -> str | None:
        if self._node_prefix:
            override = self._read_bao(f"{self._node_prefix}/{name}")
            if override is not None:
                return override
        return self._read_bao(name)

    def _read_bao(self, name: str) -> str | None:
        if not self._token:
            return None
        url = f"{self._addr}/v1/{self._mount}/data/{name}"
        try:
            data = self._request("GET", url)
            return data["data"]["data"].get("value")
        except Exception:
            return None

    def write(self, name: str, value: str) -> None:
        url = f"{self._addr}/v1/{self._mount}/data/{name}"
        self._request("POST", url, {"data": {"value": value.strip()}})

    def delete(self, name: str) -> None:
        # Remove all versions (metadata delete), matching file-backend semantics.
        url = f"{self._addr}/v1/{self._mount}/metadata/{name}"
        self._request("DELETE", url)

    def list_names(self) -> list[str]:
        url = f"{self._addr}/v1/{self._mount}/metadata?list=true"
        try:
            data = self._request("GET", url)
            keys = data.get("data", {}).get("keys", [])
            # Drop folder entries (e.g. "nodes/") — those group per-node overrides.
            return sorted(k for k in keys if not k.endswith("/"))
        except Exception:
            return []

    def _request(self, method: str, url: str, body: dict | None = None) -> dict:
        payload = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310
            url,
            data=payload,
            method=method,
            headers={
                "X-Vault-Token": self._token,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            raw = resp.read()
        return json.loads(raw) if raw else {}


def build_backend(secrets_dir: Path, settings: dict | None = None) -> SecretBackend:
    """Construct the active secret backend.

    Selection comes from ``settings`` (the ``secrets:`` block of castle.yaml), with
    environment variables overriding — so production is configured declaratively in
    castle.yaml while tests/CI can force a backend via env. Default: file.

    The OpenBao **token** is still read from the file backend (the bootstrap root of
    trust — it can't live in the vault it unlocks); everything else comes from the
    vault with no file fallback.
    """
    settings = settings or {}
    file_backend = FileSecretBackend(secrets_dir)
    kind = (os.environ.get("CASTLE_SECRET_BACKEND") or settings.get("backend") or "file").lower()
    if kind == "openbao":
        addr = os.environ.get("CASTLE_OPENBAO_ADDR") or settings.get(
            "addr"
        ) or "http://localhost:8200"
        mount = os.environ.get("CASTLE_OPENBAO_MOUNT") or settings.get("mount") or "castle"
        token_secret = os.environ.get("CASTLE_OPENBAO_TOKEN_SECRET") or settings.get(
            "token_secret"
        ) or "OPENBAO_TOKEN"
        token = file_backend.read(token_secret) or os.environ.get(
            "CASTLE_OPENBAO_TOKEN", ""
        )
        node_prefix = os.environ.get("CASTLE_OPENBAO_NODE_PREFIX") or settings.get(
            "node_prefix"
        )
        return OpenBaoBackend(addr, token, mount, node_prefix)
    return file_backend
