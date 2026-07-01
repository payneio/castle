"""Cloudflare tunnel (cloudflared) ingress config generation.

Projects ``public: true`` services onto the public internet at
``<subdomain>.<public_domain>``, bridging each to the gateway's existing internal
host site so the tunnel reuses all of Caddy's routing and TLS. The public zone and
the internal zone are deliberately different (``pub.payne.io`` vs
``civil.payne.io``) so internal subdomain names never appear in public DNS; the
ingress rewrites the Host header and TLS SNI to the *internal* name so Caddy routes
the request correctly and its wildcard cert validates.

The generated config is locally-managed (a ``config.yml`` with an explicit ingress
list), not a remotely-managed token tunnel — so the public surface is exactly the
set of ``public: true`` services, generated here, not something edited in a
dashboard.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from castle_core.config import SECRETS_DIR
from castle_core.registry import Deployment, NodeRegistry

# Cloudflared tunnel credentials (from `cloudflared tunnel create`) live here as a
# secret, one JSON per tunnel id. The generated config references this path.
TUNNEL_CREDENTIALS_DIR = SECRETS_DIR / "cloudflared"

# In acme mode Caddy serves each host site on :443 with a publicly-valid cert, so
# the tunnel origin is the gateway on 443 (not the :<gateway_port> redirect site).
_GATEWAY_ORIGIN = "https://localhost:443"


def tunnel_credentials_path(tunnel_id: str) -> Path:
    """Path to a tunnel's credentials JSON (kept in the secret store)."""
    return TUNNEL_CREDENTIALS_DIR / f"{tunnel_id}.json"


def public_deployments(registry: NodeRegistry) -> list[tuple[str, Deployment]]:
    """The deployed services flagged public (and actually routed), name-sorted."""
    return sorted(
        (name, d)
        for name, d in registry.deployed.items()
        if d.public and d.subdomain
    )


def public_hostnames(registry: NodeRegistry) -> list[str]:
    """The public hostnames that need a DNS route (``<sub>.<public_domain>``)."""
    dom = registry.node.public_domain
    if not dom:
        return []
    return [f"{d.subdomain}.{dom}" for _, d in public_deployments(registry)]


def generate_tunnel_config(registry: NodeRegistry) -> str | None:
    """Render the cloudflared ``config.yml``, or None if there's nothing to serve.

    Returns None when the tunnel isn't configured (no ``tunnel_id`` /
    ``public_domain`` / ``gateway_domain``) or no service is public — deploy then
    removes any stale config and leaves the tunnel down.
    """
    node = registry.node
    if not (node.tunnel_id and node.public_domain and node.gateway_domain):
        return None
    pubs = public_deployments(registry)
    if not pubs:
        return None

    ingress: list[dict] = []
    for _name, d in pubs:
        public_host = f"{d.subdomain}.{node.public_domain}"
        internal_host = f"{d.subdomain}.{node.gateway_domain}"
        ingress.append(
            {
                "hostname": public_host,
                "service": _GATEWAY_ORIGIN,
                # Bridge the public name to the internal host: Caddy routes by this
                # Host and its wildcard cert is issued for this SNI.
                "originRequest": {
                    "originServerName": internal_host,
                    "httpHostHeader": internal_host,
                },
            }
        )
    # Cloudflared requires a terminal catch-all; anything unmapped is refused.
    ingress.append({"service": "http_status:404"})

    config = {
        "tunnel": node.tunnel_id,
        "credentials-file": str(tunnel_credentials_path(node.tunnel_id)),
        "ingress": ingress,
    }
    return yaml.dump(config, default_flow_style=False, sort_keys=False)
