"""Caddyfile generation from castle config."""

from __future__ import annotations

from castle_core.config import GENERATED_DIR, STATIC_DIR, CastleConfig
from castle_core.registry import NodeRegistry


def find_app_dist(config: CastleConfig) -> str | None:
    """Find the app dist/ directory if it exists (legacy, checks repo)."""
    dist = config.root / "app" / "dist"
    if dist.exists() and (dist / "index.html").exists():
        return str(dist)
    return None


def generate_caddyfile(config: CastleConfig) -> str:
    """Generate Caddyfile content from castle config (legacy, uses manifest).

    Prefer generate_caddyfile_from_registry() for registry-based generation.
    """
    lines = [f":{config.gateway.port} {{"]

    # Reverse proxy for each component with proxy.caddy and expose.http
    for name, manifest in config.components.items():
        if not (
            manifest.proxy and manifest.proxy.caddy and manifest.proxy.caddy.enable
        ):
            continue
        if not (manifest.expose and manifest.expose.http):
            continue

        caddy = manifest.proxy.caddy
        http = manifest.expose.http
        path_prefix = caddy.path_prefix or f"/{name}"
        port = http.internal.port
        host = http.internal.host or "localhost"

        lines.append(f"    handle_path {path_prefix}/* {{")
        lines.append(f"        reverse_proxy {host}:{port}")
        lines.append("    }")
        lines.append("")

    # App SPA at root (must come after more-specific handle_path rules)
    app_dist = find_app_dist(config)
    if app_dist:
        lines.append("    handle {")
        lines.append(f"        root * {app_dist}")
        lines.append("        try_files {path} /index.html")
        lines.append("        file_server")
        lines.append("    }")
    else:
        # Fallback: serve from generated directory
        fallback = GENERATED_DIR / "app"
        lines.append("    handle / {")
        lines.append(f"        root * {fallback}")
        lines.append("        file_server")
        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)


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
