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


class FileSecretBackend:
    """Reads ``<secrets_dir>/<name>`` (the historical behavior)."""

    def __init__(self, secrets_dir: Path) -> None:
        self._dir = secrets_dir

    def read(self, name: str) -> str | None:
        path = self._dir / name
        if path.exists():
            return path.read_text().strip()
        return None


class OpenBaoBackend:
    """Reads from an OpenBao/Vault KV-v2 mount; falls back to ``fallback``.

    A missing key, an auth failure, or an unreachable server all fall through to
    the fallback — so a partly-migrated vault and the bootstrap token both resolve.
    """

    def __init__(
        self, addr: str, token: str, mount: str, fallback: SecretBackend
    ) -> None:
        self._addr = addr.rstrip("/")
        self._token = token
        self._mount = mount
        self._fallback = fallback

    def read(self, name: str) -> str | None:
        value = self._read_bao(name)
        if value is not None:
            return value
        return self._fallback.read(name)

    def _read_bao(self, name: str) -> str | None:
        if not self._token:
            return None
        url = f"{self._addr}/v1/{self._mount}/data/{name}"
        req = urllib.request.Request(url, headers={"X-Vault-Token": self._token})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
                data = json.load(resp)
            return data["data"]["data"].get("value")
        except Exception:
            return None


def build_backend(secrets_dir: Path) -> SecretBackend:
    """Construct the active secret backend from the environment."""
    file_backend = FileSecretBackend(secrets_dir)
    kind = os.environ.get("CASTLE_SECRET_BACKEND", "file").lower()
    if kind == "openbao":
        addr = os.environ.get("CASTLE_OPENBAO_ADDR", "http://localhost:8200")
        mount = os.environ.get("CASTLE_OPENBAO_MOUNT", "castle")
        token_secret = os.environ.get("CASTLE_OPENBAO_TOKEN_SECRET", "OPENBAO_TOKEN")
        token = file_backend.read(token_secret) or os.environ.get(
            "CASTLE_OPENBAO_TOKEN", ""
        )
        return OpenBaoBackend(addr, token, mount, fallback=file_backend)
    return file_backend
