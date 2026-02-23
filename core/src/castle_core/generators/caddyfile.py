"""Caddyfile generation from node registry."""

from __future__ import annotations

from castle_core.config import GENERATED_DIR, STATIC_DIR
from castle_core.registry import NodeRegistry


def generate_caddyfile_from_registry(registry: NodeRegistry) -> str:
    """Generate Caddyfile from the node registry.

    Static files served from ~/.castle/static/castle-app/.
    No repo-relative paths.
    """
    lines = [f":{registry.node.gateway_port} {{"]

    for name, deployed in registry.deployed.items():
        if not deployed.proxy_path or not deployed.port:
            continue

        lines.append(f"    handle_path {deployed.proxy_path}/* {{")
        lines.append(f"        reverse_proxy localhost:{deployed.port}")
        lines.append("    }")
        lines.append("")

    # SPA from static dir
    static_app = STATIC_DIR / "castle-app"
    if (static_app / "index.html").exists():
        lines.append("    handle {")
        lines.append(f"        root * {static_app}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
    else:
        fallback = GENERATED_DIR / "app"
        lines.append("    handle / {")
        lines.append(f"        root * {fallback}")
        lines.append("        file_server")
        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)
