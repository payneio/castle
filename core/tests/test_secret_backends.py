"""Tests for the pluggable secret backends (file default, OpenBao opt-in)."""

from __future__ import annotations

from pathlib import Path

from castle_core.secret_backends import (
    FileSecretBackend,
    OpenBaoBackend,
    build_backend,
)


def test_file_backend_read_hit(tmp_path: Path) -> None:
    (tmp_path / "MY_SECRET").write_text("value\n")
    assert FileSecretBackend(tmp_path).read("MY_SECRET") == "value"


def test_file_backend_read_miss(tmp_path: Path) -> None:
    assert FileSecretBackend(tmp_path).read("ABSENT") is None


def test_file_backend_write_read_list_delete(tmp_path: Path) -> None:
    b = FileSecretBackend(tmp_path)
    assert b.list_names() == []
    b.write("A", "one")
    b.write("B", "two")
    assert b.read("A") == "one"
    assert b.list_names() == ["A", "B"]
    b.delete("A")
    assert b.read("A") is None
    assert b.list_names() == ["B"]
    b.delete("ABSENT")  # no error


def test_build_backend_defaults_to_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CASTLE_SECRET_BACKEND", raising=False)
    assert isinstance(build_backend(tmp_path), FileSecretBackend)


def test_build_backend_openbao_via_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CASTLE_SECRET_BACKEND", "openbao")
    assert isinstance(build_backend(tmp_path), OpenBaoBackend)


def test_build_backend_openbao_via_settings(tmp_path: Path, monkeypatch) -> None:
    """The castle.yaml `secrets:` block selects the backend (env still overrides)."""
    monkeypatch.delenv("CASTLE_SECRET_BACKEND", raising=False)
    settings = {"backend": "openbao", "addr": "https://vault:8200", "mount": "castle"}
    assert isinstance(build_backend(tmp_path, settings), OpenBaoBackend)


def test_openbao_unreachable_returns_none_no_fallback(tmp_path: Path) -> None:
    """No file fallback: an unreachable vault returns None even if a file exists."""
    (tmp_path / "ONLY_IN_FILE").write_text("from-file")
    backend = OpenBaoBackend(addr="http://127.0.0.1:1", token="dummy", mount="castle")
    assert backend.read("ONLY_IN_FILE") is None
    assert backend.read("NOT_ANYWHERE") is None


def test_openbao_empty_token_returns_none(tmp_path: Path) -> None:
    backend = OpenBaoBackend(addr="http://127.0.0.1:8200", token="", mount="castle")
    assert backend.read("K") is None


def test_openbao_node_prefix_from_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CASTLE_SECRET_BACKEND", raising=False)
    backend = build_backend(
        tmp_path,
        {"backend": "openbao", "addr": "http://x", "node_prefix": "nodes/primer"},
    )
    assert isinstance(backend, OpenBaoBackend)
    assert backend._node_prefix == "nodes/primer"
