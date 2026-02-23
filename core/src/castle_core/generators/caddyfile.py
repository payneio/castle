"""Caddyfile generation from castle config."""

from __future__ import annotations

from castle_core.config import GENERATED_DIR, CastleConfig


def find_app_dist(config: CastleConfig) -> str | None:
    """Find the app dist/ directory if it exists."""
    dist = config.root / "app" / "dist"
    if dist.exists() and (dist / "index.html").exists():
        return str(dist)
    return None


def generate_caddyfile(config: CastleConfig) -> str:
    """Generate Caddyfile content from castle config."""
    lines = [f":{config.gateway.port} {{"]

    # Reverse proxy for each component with proxy.caddy and expose.http
    for name, manifest in config.components.items():
        if not (manifest.proxy and manifest.proxy.caddy and manifest.proxy.caddy.enable):
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
