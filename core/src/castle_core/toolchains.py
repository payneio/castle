"""Toolchain resolution — map a program's declared runtime version to a concrete
binary directory on this box.

Today this covers **node**. Programs pin their node version the ecosystem-standard
way — a ``.node-version`` / ``.nvmrc`` file, or ``package.json`` ``engines.node`` /
``volta.node`` — so a program stays castle-independent (the prime directive: regular
programs never depend on castle). Castle *reads* that pin and resolves it to an
absolute ``.../bin`` directory it can put on PATH, at both execution sites that run a
program's node:

- **build time** — the dev-verb subprocess (``stacks._build_env``), so ``castle
  program build`` uses the program's node regardless of who triggers it (your shell
  or the castle-api build executor);
- **run time** — a ``launcher: node`` service's systemd unit PATH (via
  ``deploy._build_deployed`` → the generated unit's ``Environment=PATH``).

Resolution scans nvm's versioned install layout (``CASTLE_NODE_VERSIONS_DIR``,
default ``~/.nvm/versions/node``) — the versioned dir the default tool PATH
intentionally omits. A pinned-but-not-installed version fails loud with an
actionable ``nvm install`` hint rather than surfacing later as ``node: not found``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# A pin that is a bare, exact-ish version: "24", "24.14", "24.14.1" (optional "v").
_EXACT_RE = re.compile(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")
# An installed nvm dir: v24.14.1
_INSTALLED_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)$")
# Wildcards/aliases that mean "newest installed".
_NEWEST_ALIASES = {"", "*", "x", "node", "latest", "current", "lts", "lts/*"}


class ToolchainError(Exception):
    """A program pins a toolchain version that isn't installed on this box."""


def node_versions_dir() -> Path:
    """The directory nvm installs versioned node under (env-overridable)."""
    override = os.environ.get("CASTLE_NODE_VERSIONS_DIR")
    return Path(override) if override else Path.home() / ".nvm" / "versions" / "node"


def read_node_pin(source: Path) -> str | None:
    """The node version a program pins, read the ecosystem-standard way.

    Precedence: ``.node-version`` → ``.nvmrc`` → ``package.json`` (``engines.node``,
    else ``volta.node``). Returns the raw spec string, or ``None`` if unpinned."""
    for fname in (".node-version", ".nvmrc"):
        f = source / fname
        if f.is_file():
            val = f.read_text().strip()
            if val:
                return val
    pkg = source / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        for section in ("engines", "volta"):
            node = (data.get(section) or {}).get("node")
            if isinstance(node, str) and node.strip():
                return node.strip()
    return None


def _installed() -> list[tuple[tuple[int, int, int], Path]]:
    """Installed (version, bin-dir) pairs, newest first."""
    root = node_versions_dir()
    out: list[tuple[tuple[int, int, int], Path]] = []
    if not root.is_dir():
        return out
    for child in root.iterdir():
        m = _INSTALLED_RE.match(child.name)
        if m and (child / "bin" / "node").exists():
            out.append(((int(m[1]), int(m[2]), int(m[3])), child / "bin"))
    out.sort(reverse=True)
    return out


def resolve_node_bin(source: Path | None) -> Path | None:
    """Resolve a program's pinned node version to its ``.../bin`` dir on this box.

    Returns ``None`` when the program pins nothing — castle injects no node, it does
    not guess. Raises :class:`ToolchainError` when a version *is* pinned but no
    matching version is installed.

    Matching: an exact-ish pin (``24`` / ``24.14`` / ``24.14.1``) matches installed
    versions by that precision, newest wins. A range or alias (``>=24``, ``^24.1``,
    ``lts/*``) is pinned by its leading major (or newest installed if it names none)
    — precise pins belong in ``.node-version``."""
    if source is None:
        return None
    pin = read_node_pin(source)
    if not pin:
        return None
    installed = _installed()

    def newest_or_raise() -> Path:
        if installed:
            return installed[0][1]
        raise ToolchainError(
            f"node {pin!r} pinned (in {source}) but no node is installed under "
            f"{node_versions_dir()} — run `nvm install {pin}`"
        )

    low = pin.strip().lower()
    if low in _NEWEST_ALIASES:
        return newest_or_raise()

    exact = _EXACT_RE.match(low)
    if exact:
        parts = [int(g) for g in exact.groups() if g is not None]
    else:
        # A range/alias (>=24, ^24.1, ~24, 24.x): pin by leading major only.
        major = re.search(r"\d+", low)
        if not major:
            return newest_or_raise()
        parts = [int(major.group())]
    precision = len(parts)

    for ver, bindir in installed:  # newest first
        if list(ver[:precision]) == parts:
            return bindir
    raise ToolchainError(
        f"node {pin!r} pinned (in {source}) but not installed under "
        f"{node_versions_dir()} — run `nvm install {pin}`"
    )
