"""Secrets management — routes through the active backend (file or OpenBao)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_core.config import SECRETS_DIR, _secrets_settings
from castle_core.secret_backends import OpenBaoBackend, build_backend

from castle_api.config import get_registry

router = APIRouter(prefix="/secrets", tags=["secrets"])


def _backend():
    # Same selection as the rest of castle (castle.yaml `secrets:` block).
    return build_backend(SECRETS_DIR, _secrets_settings())


class SecretValue(BaseModel):
    value: str


@router.get("")
def list_secrets() -> list[str]:
    """List all secret names (not values)."""
    return _backend().list_names()


@router.get("/info")
def secrets_info() -> dict:
    """The active backend + whether this node may write (for the UI)."""
    settings = _secrets_settings()
    backend = _backend()
    kind = "openbao" if isinstance(backend, OpenBaoBackend) else "file"
    role = get_registry().node.role
    # File is always writable; a vault follower holds a read-only token.
    writable = kind == "file" or role == "authority"
    return {
        "backend": kind,
        "addr": settings.get("addr") if kind == "openbao" else None,
        "role": role,
        "writable": writable,
    }


@router.get("/{name}")
def get_secret(name: str) -> dict:
    """Get a secret value."""
    _validate_name(name)
    value = _backend().read(name)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{name}' not found",
        )
    return {"name": name, "value": value}


@router.put("/{name}")
def set_secret(name: str, body: SecretValue) -> dict:
    """Set a secret value."""
    _validate_name(name)
    _backend().write(name, body.value)
    return {"name": name, "ok": True}


@router.delete("/{name}")
def delete_secret(name: str) -> dict:
    """Delete a secret."""
    _validate_name(name)
    _backend().delete(name)
    return {"name": name, "ok": True}


def _validate_name(name: str) -> None:
    """Reject path traversal attempts."""
    if "/" in name or "\\" in name or ".." in name or not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid secret name",
        )
