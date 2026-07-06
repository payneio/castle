"""Tests for toolchain (node) version resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from castle_core import toolchains
from castle_core.toolchains import (
    ToolchainError,
    read_node_pin,
    resolve_node_bin,
)


def _install(root: Path, *versions: str) -> None:
    """Create fake nvm-style installs: <root>/vX.Y.Z/bin/node."""
    for v in versions:
        bindir = root / v / "bin"
        bindir.mkdir(parents=True)
        (bindir / "node").write_text("#!/bin/sh\n")


@pytest.fixture
def nvm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "nvm"
    root.mkdir()
    monkeypatch.setenv("CASTLE_NODE_VERSIONS_DIR", str(root))
    return root


class TestReadNodePin:
    def test_node_version_file(self, tmp_path: Path) -> None:
        (tmp_path / ".node-version").write_text("24.14.1\n")
        assert read_node_pin(tmp_path) == "24.14.1"

    def test_nvmrc_when_no_node_version(self, tmp_path: Path) -> None:
        (tmp_path / ".nvmrc").write_text("20\n")
        assert read_node_pin(tmp_path) == "20"

    def test_node_version_wins_over_nvmrc(self, tmp_path: Path) -> None:
        (tmp_path / ".node-version").write_text("24\n")
        (tmp_path / ".nvmrc").write_text("20\n")
        assert read_node_pin(tmp_path) == "24"

    def test_package_json_engines(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"engines": {"node": ">=22"}}')
        assert read_node_pin(tmp_path) == ">=22"

    def test_package_json_volta_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"volta": {"node": "18.20.0"}}')
        assert read_node_pin(tmp_path) == "18.20.0"

    def test_unpinned(self, tmp_path: Path) -> None:
        assert read_node_pin(tmp_path) is None

    def test_malformed_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{not json")
        assert read_node_pin(tmp_path) is None


class TestResolveNodeBin:
    def test_unpinned_returns_none(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.14.1")
        assert resolve_node_bin(tmp_path) is None

    def test_none_source(self) -> None:
        assert resolve_node_bin(None) is None

    def test_exact_match(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.14.1", "v20.10.0")
        (tmp_path / ".node-version").write_text("24.14.1")
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.1" / "bin"

    def test_major_prefix_picks_newest(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.1.0", "v24.14.1", "v24.9.0", "v20.10.0")
        (tmp_path / ".node-version").write_text("24")
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.1" / "bin"

    def test_major_minor_prefix(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.14.1", "v24.14.9", "v24.9.0")
        (tmp_path / ".node-version").write_text("24.14")
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.9" / "bin"

    def test_engines_range_matches_major(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.14.1", "v20.10.0")
        (tmp_path / "package.json").write_text('{"engines": {"node": ">=24"}}')
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.1" / "bin"

    def test_caret_range_matches_major(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.1.0", "v24.14.1")
        (tmp_path / "package.json").write_text('{"engines": {"node": "^24.1.0"}}')
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.1" / "bin"

    def test_alias_lts_picks_newest(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v24.14.1", "v20.10.0")
        (tmp_path / ".nvmrc").write_text("lts/*")
        assert resolve_node_bin(tmp_path) == nvm / "v24.14.1" / "bin"

    def test_pinned_but_not_installed_raises(self, tmp_path: Path, nvm: Path) -> None:
        _install(nvm, "v20.10.0")
        (tmp_path / ".node-version").write_text("24")
        with pytest.raises(ToolchainError, match="nvm install"):
            resolve_node_bin(tmp_path)

    def test_no_installs_raises_for_alias(self, tmp_path: Path, nvm: Path) -> None:
        (tmp_path / ".nvmrc").write_text("node")
        with pytest.raises(ToolchainError):
            resolve_node_bin(tmp_path)

    def test_missing_bin_not_counted(self, tmp_path: Path, nvm: Path) -> None:
        # A version dir with no bin/node is not a usable install.
        (nvm / "v24.14.1").mkdir(parents=True)
        (tmp_path / ".node-version").write_text("24")
        with pytest.raises(ToolchainError):
            resolve_node_bin(tmp_path)

    def test_default_dir_is_nvm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CASTLE_NODE_VERSIONS_DIR", raising=False)
        assert toolchains.node_versions_dir() == Path.home() / ".nvm" / "versions" / "node"
