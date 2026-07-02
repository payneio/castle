"""Reconcile public DNS (Cloudflare CNAMEs) for tunnel-exposed services.

Castle owns the CNAMEs in the public zone that point at its Cloudflare tunnel:
on deploy it creates one per public service and deletes any that point at this
tunnel but no longer correspond to a public service. It **only ever touches
records whose content is `<tunnel_id>.cfargotunnel.com`** — never other records in
the zone — so a hand-managed A/CNAME in the same zone is safe.

Needs a Cloudflare API token with **DNS:Edit** on the public zone (Cloudflare's
"Edit zone DNS" template — that single permission both resolves the zone by name
and edits records; no separate Zone:Read is needed), stored at
`~/.castle/secrets/CLOUDFLARE_PUBLIC_DNS_TOKEN`. Absent → this is a no-op and the
caller falls back to surfacing the manual `cloudflared tunnel route dns` hints.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from castle_core.config import SECRETS_DIR

_API = "https://api.cloudflare.com/client/v4"

# Secret holding a Cloudflare token scoped to the PUBLIC zone (Zone:DNS:Edit).
# Distinct from CLOUDFLARE_API_TOKEN (ACME, the internal civil zone) because the
# public zone is typically a separate zone/account.
PUBLIC_DNS_TOKEN = "CLOUDFLARE_PUBLIC_DNS_TOKEN"


def public_dns_token() -> str | None:
    """The public-zone DNS token from secrets, or None if not configured."""
    path = SECRETS_DIR / PUBLIC_DNS_TOKEN
    if path.exists():
        return path.read_text().strip() or None
    return None


def _api(token: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (fixed API host)
        return json.loads(resp.read())


def reconcile_public_dns(
    public_domain: str | None,
    tunnel_id: str | None,
    desired_hosts: list[str],
    messages: list[str],
    token: str | None = None,
) -> bool:
    """Make the public zone's tunnel CNAMEs exactly `desired_hosts`.

    Creates missing CNAMEs (proxied → the tunnel) and deletes castle-managed ones
    (content == `<tunnel_id>.cfargotunnel.com`) not in `desired_hosts`. Never
    touches records pointing elsewhere.

    Returns True if reconciliation was attempted (a token was configured) — the
    caller then suppresses the manual route hints — or False if skipped (no token /
    no tunnel / no public domain), so the caller can fall back to those hints.
    """
    token = token or public_dns_token()
    if not (token and public_domain and tunnel_id):
        return False
    target = f"{tunnel_id}.cfargotunnel.com"
    try:
        zres = (_api(token, "GET", f"/zones?name={public_domain}").get("result")) or []
        if not zres:
            messages.append(
                f"Warning: DNS token can't see zone '{public_domain}' — public "
                "CNAMEs not reconciled. The token needs DNS:Edit (Cloudflare's "
                f"'Edit zone DNS' template) scoped to {public_domain}."
            )
            return False
        zone_id = zres[0]["id"]
        # Castle-managed set = existing CNAMEs whose content is our tunnel.
        recs = _api(
            token, "GET", f"/zones/{zone_id}/dns_records?type=CNAME&per_page=100"
        ).get("result") or []
        managed = {r["name"]: r["id"] for r in recs if r.get("content") == target}

        desired = set(desired_hosts)
        created = sorted(desired - set(managed))
        removed = sorted(set(managed) - desired)
        for host in created:
            _api(
                token,
                "POST",
                f"/zones/{zone_id}/dns_records",
                {"type": "CNAME", "name": host, "content": target, "proxied": True},
            )
        for host in removed:
            _api(token, "DELETE", f"/zones/{zone_id}/dns_records/{managed[host]}")

        if created or removed:
            parts = []
            if created:
                parts.append(f"+{len(created)} ({', '.join(created)})")
            if removed:
                parts.append(f"-{len(removed)} ({', '.join(removed)})")
            messages.append(f"Public DNS reconciled: {' '.join(parts)}")
        else:
            messages.append(f"Public DNS up to date ({len(desired)} CNAME(s)).")
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
