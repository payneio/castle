"""Caddyfile generation from node registry."""

from __future__ import annotations

from pathlib import Path

from castle_core.config import SPECS_DIR
from castle_core.registry import NodeRegistry


def generate_caddyfile_from_registry(
    registry: NodeRegistry,
    remote_registries: dict[str, NodeRegistry] | None = None,
) -> str:
    """Generate Caddyfile from the node registry.

    Static files served from ~/.castle/artifacts/content/castle-app/.
    No repo-relative paths.

    If remote_registries is provided, cross-node routes are added for
    remote services whose proxy_path doesn't conflict with local ones.
    """
    lines = [f":{registry.node.gateway_port} {{"]

    # Track local proxy paths for precedence
    local_paths: set[str] = set()

    for name, deployed in registry.deployed.items():
        if not deployed.proxy_path:
            continue
        # Need either a local port or a remote base_url to proxy to
        if not deployed.port and not deployed.base_url:
            continue

        local_paths.add(deployed.proxy_path)
        target = deployed.base_url or f"localhost:{deployed.port}"
        lines.append(f"    handle_path {deployed.proxy_path}/* {{")
        lines.append(f"        reverse_proxy {target}")
        lines.append("    }")
        lines.append("")

    # Remote routes (cross-node) — local paths take precedence
    if remote_registries:
        for hostname, remote_reg in remote_registries.items():
            for name, deployed in remote_reg.deployed.items():
                if not deployed.proxy_path or not deployed.port:
                    continue
                if deployed.proxy_path in local_paths:
                    continue

                local_paths.add(deployed.proxy_path)
                lines.append(f"    # {name} on {hostname}")
                lines.append(f"    handle_path {deployed.proxy_path}/* {{")
                lines.append(f"        reverse_proxy {hostname}:{deployed.port}")
                lines.append("    }")
                lines.append("")

    # Static frontends — served IN PLACE from each program's repo build output.
    # A behavior=frontend program with no service is static; Caddy roots directly
    # at <source>/<build.outputs[0]> (no central copy). castle-app is the root app
    # (served at /); other static frontends mount at /<name>.
    root_serve = _root_static_serve(lines, local_paths)

    if root_serve is not None:
        lines.append("    handle {")
        lines.append(f"        root * {root_serve}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
    else:
        fallback = SPECS_DIR / "app"
        lines.append("    handle / {")
        lines.append(f"        root * {fallback}")
        lines.append("        file_server")
        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)


def _root_static_serve(lines: list[str], local_paths: set[str]) -> Path | None:
    """Emit handle_path blocks for non-root static frontends; return the root app's
    serve dir (castle-app), or None. Static frontends are served from their repo
    build output in place — no copy into a central content dir."""
    try:
        from castle_core.config import load_config

        config = load_config()
    except Exception:
        return None

    root_serve: Path | None = None
    for name, prog in sorted(config.programs.items()):
        if prog.behavior != "frontend" or not prog.source:
            continue
        if not (prog.build and prog.build.outputs):
            continue
        if name in config.services:  # self-serving frontend → handled as a proxy route
            continue
        serve_dir = Path(prog.source) / prog.build.outputs[0]
        if name == "castle-app":
            root_serve = serve_dir
            continue
        path_prefix = f"/{name}"
        if path_prefix in local_paths:
            continue
        local_paths.add(path_prefix)
        lines.append(f"    handle_path {path_prefix}/* {{")
        lines.append(f"        root * {serve_dir}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
        lines.append("")
    return root_serve
