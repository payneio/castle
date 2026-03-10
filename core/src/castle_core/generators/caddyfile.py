"""Caddyfile generation from node registry."""

from __future__ import annotations

from castle_core.config import CONTENT_DIR, SPECS_DIR
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
        if not deployed.proxy_path or not deployed.port:
            continue

        local_paths.add(deployed.proxy_path)
        lines.append(f"    handle_path {deployed.proxy_path}/* {{")
        lines.append(f"        reverse_proxy localhost:{deployed.port}")
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

    # Static frontends from ~/.castle/static/<name>/
    # Any directory with an index.html gets served as a SPA at its name prefix.
    # castle-app is special-cased to serve at the root (no prefix).
    if CONTENT_DIR.is_dir():
        for app_dir in sorted(CONTENT_DIR.iterdir()):
            if not app_dir.is_dir() or not (app_dir / "index.html").exists():
                continue
            if app_dir.name == "castle-app":
                continue  # handled below as root fallback
            path_prefix = f"/{app_dir.name}"
            if path_prefix in local_paths:
                continue
            local_paths.add(path_prefix)
            lines.append(f"    handle_path {path_prefix}/* {{")
            lines.append(f"        root * {app_dir}")
            lines.append("        try_files {path} /index.html")
            lines.append("        file_server")
            lines.append("    }")
            lines.append("")

    # castle-app SPA at root (fallback)
    static_app = CONTENT_DIR / "castle-app"
    if (static_app / "index.html").exists():
        lines.append("    handle {")
        lines.append(f"        root * {static_app}")
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
