"""Regenerate the gateway with cross-node (remote) routes from the live mesh.

Local routes come from `castle apply` (static). Remote routes are dynamic — they
appear/vanish as peers join/leave — so the API owns them: on a mesh change it
re-renders the Caddyfile (same generator `apply` uses, plus remote routes for
online peers) and reloads the gateway iff the content changed.

Safety: with no cross-node `requires`, the output equals the local-only Caddyfile,
so this is a verified no-op until this node actually consumes a peer service.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess

from castle_core.config import SPECS_DIR
from castle_core.generators.caddyfile import generate_caddyfile_from_registry

from castle_api.config import get_registry
from castle_api.mesh import mesh_state

logger = logging.getLogger(__name__)

_GATEWAY_UNIT = "castle-castle-gateway.service"


def _regenerate(reload: bool) -> bool:
    try:
        reg = get_registry()
    except Exception:
        return False
    remotes = {h: n.registry for h, n in mesh_state.all_nodes().items()}
    try:
        content = generate_caddyfile_from_registry(reg, remotes)
    except Exception:
        logger.exception("mesh gateway: Caddyfile generation failed")
        return False
    path = SPECS_DIR / "Caddyfile"
    old = path.read_text() if path.exists() else ""
    if content == old:
        return False
    path.write_text(content)
    logger.info("mesh gateway: Caddyfile updated with cross-node routes")
    if reload:
        subprocess.run(
            ["systemctl", "--user", "reload", _GATEWAY_UNIT], check=False
        )
    return True


async def refresh_remote_routes(reload: bool = True) -> bool:
    """Async wrapper — runs the blocking regen off the event loop."""
    return await asyncio.to_thread(_regenerate, reload)
