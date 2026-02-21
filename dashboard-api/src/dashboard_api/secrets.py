"""Secrets management — read and write ~/.castle/secrets/."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from castle_cli.config import SECRETS_DIR

router = APIRouter(prefix="/secrets", tags=["secrets"])


class SecretValue(BaseModel):
    value: str


@router.get("")
def list_secrets() -> list[str]:
    """List all secret names (not values)."""
    if not SECRETS_DIR.exists():
        return []
    return sorted(f.name for f in SECRETS_DIR.iterdir() if f.is_file())


@router.get("/{name}")
def get_secret(name: str) -> dict:
    """Get a secret value."""
    _validate_name(name)
    path = SECRETS_DIR / name
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{name}' not found",
        )
    return {"name": name, "value": path.read_text().strip()}


@router.put("/{name}")
def set_secret(name: str, body: SecretValue) -> dict:
    """Set a secret value."""
    _validate_name(name)
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    path = SECRETS_DIR / name
    path.write_text(body.value.strip() + "\n")
    return {"name": name, "ok": True}


@router.delete("/{name}")
def delete_secret(name: str) -> dict:
    """Delete a secret."""
    _validate_name(name)
    path = SECRETS_DIR / name
    if path.exists():
        path.unlink()
    return {"name": name, "ok": True}


def _validate_name(name: str) -> None:
    """Reject path traversal attempts."""
    if "/" in name or "\\" in name or ".." in name or not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid secret name",
        )
