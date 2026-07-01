# Public exposure via Cloudflare Tunnel

Castle is LAN-only by default: services with `proxy: true` are reachable at
`<name>.<gateway.domain>` (e.g. `<name>.civil.payne.io`) through split DNS, and
nothing is on the public internet. This document sets up a **per-service public
toggle** — flip `public: true` on a service and it's also reachable from the public
internet at `<name>.<gateway.public_domain>`, via a Cloudflare Tunnel.

## How it works

- **Default private.** `public` defaults to `false`; a service is public only when
  you say so, and `public: true` requires `proxy: true` (it projects an
  already-routed subdomain).
- **Separate public zone.** Public services publish at a *different* zone
  (`<name>.pub.payne.io`), so internal subdomain names never appear in public DNS.
- **The tunnel bridges public → internal.** `cloudflared` dials **outbound** to
  Cloudflare (no inbound holes, no public IP needed) and forwards each public
  hostname to the gateway on `:443`, rewriting the Host header and TLS SNI to the
  *internal* name so Caddy routes it and its wildcard cert validates. The public
  surface is exactly the set of `public: true` services — `castle deploy` generates
  the ingress from the registry.
- **One kill switch.** Stop `castle-tunnel` → instantly nothing is public.

```
foo.pub.payne.io  ──(Cloudflare edge, public cert)──▶  cloudflared (outbound)
   └─▶ https://localhost:443, Host/SNI = foo.civil.payne.io  ──▶  Caddy ──▶ service
```

## One-time setup (owner steps — needs Cloudflare login)

```bash
# 1. Install cloudflared (Debian/Ubuntu) — it's NOT in the default repos, so add
#    Cloudflare's apt repo first:
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared

# 2. Authenticate and create the tunnel (opens a browser to pick the zone)
cloudflared tunnel login
cloudflared tunnel create castle          # prints a tunnel UUID + writes creds JSON

# 3. Move the credentials into Castle's secret store (path the generator expects)
mkdir -p ~/.castle/secrets/cloudflared
TID=<the-uuid-from-step-2>
mv ~/.cloudflared/$TID.json ~/.castle/secrets/cloudflared/$TID.json
chmod 600 ~/.castle/secrets/cloudflared/$TID.json

# 4. Tell Castle the public zone + tunnel id (in ~/.castle/castle.yaml)
#    gateway:
#      ...
#      public_domain: pub.payne.io
#      tunnel_id: <the-uuid>
```

Then create the tunnel service at `~/.castle/services/castle-tunnel.yaml`:

```yaml
description: Cloudflare tunnel — public exposure for public:true services
run:
  runner: command
  argv:
    - cloudflared
    - tunnel
    - --no-autoupdate
    - --config
    - /home/payne/.castle/artifacts/specs/cloudflared.yml
    - run
manage:
  systemd: {}
```

Bring it online:

```bash
castle deploy                       # writes cloudflared.yml from public services
castle service enable castle-tunnel # start the tunnel
```

## Using the toggle

Mark a service public in its `services/<name>.yaml`:

```yaml
proxy: true      # required — the service must be routed
public: true     # also expose at <name>.pub.payne.io via the tunnel
```

Then deploy and route DNS (a CNAME `<name>.pub.payne.io → <tunnel>.cfargotunnel.com`,
created once per public host — `castle deploy` prints the exact command):

```bash
castle deploy
cloudflared tunnel route dns <tunnel-id> <name>.pub.payne.io
```

`castle deploy` regenerates `~/.castle/artifacts/specs/cloudflared.yml` from the
current set of public services and restarts `castle-tunnel`. Flip `public` back to
`false` (or remove it) and redeploy to un-expose — the hostname drops out of the
ingress immediately.

## The part that isn't the tunnel

Reachability is the easy half. Anything public also needs, per service:

- **Auth.** "Public" rarely means "no auth." Put login in front — Cloudflare Access
  at the edge, an auth proxy, or the app's own (Supabase GoTrue). A public app whose
  privacy matters must actually enforce it (auth-gated shell + signed storage URLs,
  not just row-level security).
- **Hardening.** Rate-limiting / WAF (free on Cloudflare), and never expose admin or
  substrate-Studio surfaces.

## Notes

- Requires `gateway.tls: acme` (the tunnel forwards to the gateway's real-cert
  `:443` host sites). On an `off`/`internal` gateway the origin bridge doesn't apply.
- Cloudflare terminates TLS at the edge (it can see plaintext). For a
  no-third-party-in-path variant, the same `public: true` model can drive a
  self-hosted VPS + WireGuard edge instead — the toggle and generator stay; only the
  transport changes.
