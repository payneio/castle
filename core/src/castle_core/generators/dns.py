"""Reconcile public DNS (Cloudflare CNAMEs) for tunnel-exposed services.

Castle owns the CNAMEs — across every zone the token can see — that point at its
Cloudflare tunnel: on deploy it creates one per public host (each routed to the
accessible zone whose name is its longest suffix, so apex and multi-zone hosts both
work) and deletes any that point at this tunnel but no longer correspond to a
public service. It **only ever touches records whose content is
`<tunnel_id>.cfargotunnel.com`** — never other records in a zone — so a
hand-managed A/CNAME in the same zone is safe.

Needs a Cloudflare API token with **DNS:Edit** on every target zone (Cloudflare's
"Edit zone DNS" template — that single permission both lists the accessible zones
and edits records; no separate Zone:Read is needed), stored at
`~/.castle/secrets/CLOUDFLARE_PUBLIC_DNS_TOKEN`. Absent → this is a no-op and the
caller falls back to surfacing the manual `cloudflared tunnel route dns` hints.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

_API = "https://api.cloudflare.com/client/v4"

# Secret holding a Cloudflare token scoped to the PUBLIC zone (Zone:DNS:Edit).
# Distinct from CLOUDFLARE_API_TOKEN (ACME, the internal civil zone) because the
# public zone is typically a separate zone/account.
PUBLIC_DNS_TOKEN = "CLOUDFLARE_PUBLIC_DNS_TOKEN"


def public_dns_token() -> str | None:
    """The public-zone DNS token from the active secret backend, or None."""
    from castle_core.config import read_secret

    return read_secret(PUBLIC_DNS_TOKEN) or None


def _api(token: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed API host)
        return json.loads(resp.read())


def _zone_for(host: str, zones: list[dict]) -> dict | None:
    """The visible zone whose name is the longest suffix of ``host`` (or None).

    Longest-suffix so an apex (``example.com`` in zone ``example.com``) and a
    subdomain in any accessible zone both resolve, even when zones nest.
    """
    matches = [
        z
        for z in zones
        if host == z["name"] or host.endswith("." + z["name"])
    ]
    return max(matches, key=lambda z: len(z["name"])) if matches else None


def reconcile_public_dns(
    tunnel_id: str | None,
    desired_hosts: list[str],
    messages: list[str],
    token: str | None = None,
) -> bool:
    """Make the tunnel CNAMEs across every accessible zone exactly `desired_hosts`.

    Each desired host is routed to the accessible zone whose name is its longest
    suffix (so apex hosts and hosts in different zones are handled), then per zone
    castle creates missing CNAMEs (proxied → the tunnel; Cloudflare flattens apex
    CNAMEs) and deletes castle-managed ones (content == `<tunnel_id>.cfargotunnel.com`)
    no longer desired. Never touches records pointing elsewhere. Scanning every
    visible zone also cleans up stale CNAMEs after a host moves zones or all public
    services are removed.

    Returns True if reconciliation was attempted (a token was configured) — the
    caller then suppresses the manual route hints — or False if skipped (no token /
    no tunnel), so the caller can fall back to those hints.
    """
    token = token or public_dns_token()
    if not (token and tunnel_id):
        return False
    target = f"{tunnel_id}.cfargotunnel.com"
    try:
        zones = (_api(token, "GET", "/zones?per_page=50").get("result")) or []
        if not zones:
            messages.append(
                "Warning: DNS token can't see any zone — public CNAMEs not "
                "reconciled. The token needs DNS:Edit (Cloudflare's 'Edit zone "
                "DNS' template) on the target zone(s)."
            )
            return True

        # Route each desired host to its zone (longest-suffix match). Hosts with no
        # accessible zone can't be created — surface them rather than silently drop.
        desired_by_zone: dict[str, set[str]] = {z["id"]: set() for z in zones}
        for host in desired_hosts:
            z = _zone_for(host, zones)
            if z is None:
                messages.append(
                    f"Warning: no accessible Cloudflare zone for public host "
                    f"'{host}' — its CNAME was not created. The DNS token needs "
                    f"DNS:Edit on that host's zone."
                )
                continue
            desired_by_zone[z["id"]].add(host)

        created: list[str] = []
        removed: list[str] = []
        # Reconcile every visible zone (not just those with desired hosts) so a
        # CNAME orphaned by a host moving zones / going internal is cleaned up.
        for z in zones:
            zone_id = z["id"]
            recs = _api(
                token, "GET", f"/zones/{zone_id}/dns_records?type=CNAME&per_page=100"
            ).get("result") or []
            managed = {r["name"]: r["id"] for r in recs if r.get("content") == target}
            desired = desired_by_zone[zone_id]
            for host in sorted(desired - set(managed)):
                _api(
                    token,
                    "POST",
                    f"/zones/{zone_id}/dns_records",
                    {"type": "CNAME", "name": host, "content": target, "proxied": True},
                )
                created.append(host)
            for host in sorted(set(managed) - desired):
                _api(token, "DELETE", f"/zones/{zone_id}/dns_records/{managed[host]}")
                removed.append(host)

        if created or removed:
            parts = []
            if created:
                parts.append(f"+{len(created)} ({', '.join(sorted(created))})")
            if removed:
                parts.append(f"-{len(removed)} ({', '.join(sorted(removed))})")
            messages.append(f"Public DNS reconciled: {' '.join(parts)}")
        else:
            messages.append(f"Public DNS up to date ({len(desired_hosts)} CNAME(s)).")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        hint = ""
        if e.code == 403:
            # Reads can succeed while writes 403 — the token has DNS:Read but not
            # DNS:Edit. Point at the fix rather than the raw body.
            hint = (
                "  → the token needs DNS:Edit (write), not just read — use "
                "Cloudflare's 'Edit zone DNS' template."
            )
        messages.append(f"Warning: public DNS reconcile failed (HTTP {e.code}): {body}{hint}")
        return True  # token was present; don't also print stale manual hints
    except Exception as e:  # noqa: BLE001 — DNS is best-effort; never fail a deploy
        messages.append(f"Warning: public DNS reconcile failed: {e}")
        return True
