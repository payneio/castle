# DNS & TLS in Castle

How services on a Castle node become reachable by name and trusted over HTTPS —
while staying **internal-only** (no external exposure). This is the conceptual
companion to the field-level gateway reference in
[registry.md](registry.md#proxy--how-the-gateway-routes-to-it).

Two independent questions decide whether `https://foo.example/` works from a
browser on your LAN:

1. **Resolve** — does the name `foo.example` point at the Castle node? *(DNS)*
2. **Trust** — is the certificate the node serves one the browser accepts? *(TLS)*

Castle answers #1 by leaning on your LAN's own DNS, and #2 with a per-node choice
of three TLS modes. They're orthogonal: you pick a resolution strategy and a trust
strategy, and any working combination is fine.

## The gateway is the single ingress

Every reachable service goes through the Caddy **gateway** (`:9000` by default). A
gateway route maps a public **address** to a **target**. Two address shapes matter
for DNS and TLS:

- **path prefix** (`/foo`) — reached at `http://<node>:9000/foo/`. Shares the
  node's own name/port; needs no per-service DNS. Caddy **strips** the prefix, so
  this only suits apps that don't assume they live at the origin root.
- **host route** (`foo.lan`, `foo.example.com`) — reached at `https://foo.…/`. A
  whole hostname proxied to the backend root, nothing stripped. This is the shape
  that gets its own DNS name and its own TLS cert.

> **Rule of thumb:** a service that needs HTTPS, a real origin, WebSockets, or
> root-relative asset URLs wants a **host route**. Path prefixes are for simple,
> prefix-agnostic backends. See
> [registry.md](registry.md#path-prefix-vs-host-route--pick-by-whether-the-app-is-prefix-aware)
> for the failure modes of putting a root-based app under a stripped prefix.

Only host routes are the subject of the rest of this document — they're what DNS
and TLS act on.

## DNS: making a name resolve to the node

A host route does nothing until `foo.…` resolves **to this node** on the clients
that will use it. Castle does **not** run DNS; it relies on whatever already serves
your LAN. Two facts shape the approach:

- **Resolve on the clients that matter.** A name only needs to resolve for the
  devices that browse it. That's usually your LAN's DHCP/DNS authority — often the
  router — not a central or mesh resolver.
- **One wildcard beats many records.** A single wildcard entry routes every
  subdomain of a zone to the node, so each new host-routed service works with no
  further DNS edits.

### Split-horizon: internal names, no public exposure

The names Castle serves resolve **only inside the LAN**. For a private zone this is
automatic; for a public domain you own, it's deliberate split-horizon — your LAN
resolver answers with the node's private IP, and the **public** zone has no `A`
records for the services, so nothing is reachable from the internet.

### Two zone styles

| Zone style | Example | Who's authoritative | Wildcard record |
|------------|---------|---------------------|-----------------|
| **private TLD** | `*.civil.lan` | the LAN router/DHCP server (owns `.lan`) | `address=/civil.lan/<node-ip>` |
| **subdomain of a public domain** | `*.civil.payne.io` | your public DNS host (e.g. Cloudflare), but **answered internally** by a LAN resolver | `address=/civil.payne.io/<node-ip>` |

Both give the same result — every `*.<zone>` name resolves to the node's LAN IP.
The difference is which TLS modes each can use (below): a private TLD like `.lan`
**cannot** get a publicly-trusted cert (it isn't a real domain), while a real
subdomain can.

### Worked topology (this network)

- The **router** (`192.168.8.1`, a GL.iNet box) owns the `.lan` zone: it
  auto-registers DHCP hostnames (`civil.lan`) and answers `*.lan`. Unknown `.lan`
  names are **not** forwarded upstream — the router keeps that zone to itself. A
  `*.civil.lan` wildcard therefore lives on the **router**.
- The router **forwards everything else** (including `*.payne.io`) to
  **wild-central**'s dnsmasq. So a `*.civil.payne.io` wildcard lives on
  **wild-central** (`/etc/dnsmasq.d/civil-payne.conf`,
  `address=/civil.payne.io/192.168.8.222`), which the router already routes to.
  `payne.io`'s **public** authority is Cloudflare, which holds no `A` records for
  these names — so `civil.payne.io` services resolve on the LAN and nowhere else.

Pin the node's IP with a **DHCP reservation** — the wildcard hardcodes it, so a
drifting dynamic lease would break every host route at once.

## TLS: three trust modes

`gateway.tls` (in `castle.yaml`) picks how host routes are served. It's a per-node
choice; the modes are mutually exclusive.

| `gateway.tls` | What the browser gets | Client setup | Use when |
|---------------|-----------------------|--------------|----------|
| `off` *(default)* | plain HTTP on `:9000` | none | you don't need HTTPS; localhost-only tools |
| `internal` | HTTPS from Caddy's **local CA** | **install & trust the CA** on every device | LAN with a private `.lan` zone, few devices you control |
| `acme` | HTTPS from a **real Let's Encrypt wildcard** | **nothing** | you own a domain; multiple devices (phones, etc.) |

### `off` — plain HTTP

The gateway generates `auto_https off` and listens on a bare `:9000`. Reach it at
`http://<node>:9000/`. Simple, but a non-`localhost` HTTP page is **not** a browser
"secure context" (see below), and there's no encryption.

### `internal` — Caddy's local CA

Each host route becomes its own `tls internal` HTTPS site, signed by a CA Caddy
generates on the node. Browsers get a real secure context — but only if they
**trust that private CA**, which means distributing the root cert to every device's
system/browser trust store. That's the catch: some platforms (notably Android
browsers, and Firefox everywhere, which uses its own store) make installing a
custom CA painful or impossible. Castle helps by exposing the public root at
`GET /gateway/ca.crt` with a dashboard download button — but the per-device trust
step is unavoidable, and it's why `internal` doesn't scale past a handful of
machines you fully control.

Good fit: a `.lan` zone (which can't get a public cert anyway) with a couple of
trusted laptops.

### `acme` — real Let's Encrypt wildcard via DNS-01

The gateway obtains a genuine, publicly-trusted **wildcard** cert (`*.<domain>`)
from Let's Encrypt using a **DNS-01** challenge. Every browser and phone trusts it
with **zero setup** — while the services stay internal-only.

How it stays internal:

- **DNS-01 proves ownership without exposure.** Caddy writes a transient
  `_acme-challenge.<domain>` TXT record to the **public** zone via your DNS
  provider's API; Let's Encrypt reads it over public DNS and issues the cert. No
  inbound connection, no open port, no public `A` record for any service is ever
  needed. (HTTP-01 can't validate a wildcard, so DNS-01 — and thus a provider API
  token — is mandatory here.)
- **Only LAN DNS points at the node.** The public zone stays `A`-record-free; your
  LAN resolver answers `*.<domain>` with the private IP. Public internet sees
  nothing.

One `*.<domain>` site means a **single cert** covers every host route, and Caddy
**auto-renews** it — adding a service needs no new cert and no DNS-01 round trip.
Host-route subdomains are derived from the **service name**: a service opts into a
host route with `proxy.caddy.host`, and it's published at `<service>.<domain>`.

This is the recommended mode when you own a domain and want to reach services from
arbitrary devices.

## Why HTTPS at all — the secure-context requirement

Beyond eavesdropping protection, HTTPS unlocks browser capabilities gated to a
**secure context**: `crypto.subtle` (WebCrypto), service workers, and anything
built on them (device identity, end-to-end crypto). Browsers treat only `https://`
and `http://localhost` as secure — a plain-HTTP page on a LAN hostname is **not**,
so such apps break there. That's the concrete reason to move a host route to
`internal` or `acme` rather than leaving it on `off`.

Note: a host served over HTTPS has its own **origin** (`https://foo.example`, no
port). An app that allowlists origins, or an OAuth/token flow, must include the new
origin — moving a service between modes changes its origin.

## Putting a service on trusted HTTPS — the recipe

1. **Give it a host route.** In the service's `proxy.caddy`, set `host:` (drop any
   `path_prefix`). The literal host value is used as-is in `internal` mode; in
   `acme` mode the published name is derived as `<service>.<domain>`.
2. **Make the name resolve.** Add (or rely on) the LAN wildcard for the zone
   (§DNS). Verify: `dig +short <service>.<zone>` → the node's IP.
3. **Pick a trust mode** on the gateway (`gateway.tls`), plus the operational
   prerequisites for it (below).
4. **Deploy & reload:** `castle deploy` regenerates the Caddyfile and reloads Caddy.
5. **Update the app's origin allowlist** if it has one (§secure context).

## Operational prerequisites

Both HTTPS modes need the gateway to bind privileged ports; `acme` also needs a
plugin-enabled Caddy and a DNS token.

- **Bind `:443`/`:80`.** Caddy serves HTTPS on `:443` (and redirects `:80`). A
  user-level gateway can't bind privileged ports under `NoNewPrivileges`, so lower
  the floor once: `net.ipv4.ip_unprivileged_port_start=80`, persisted in
  `/etc/sysctl.d/`. (This beats `setcap`, which `NoNewPrivileges=true` would void.)
- **`acme` only — a DNS-plugin Caddy.** Stock Caddy has no DNS-provider modules.
  Build one: `./install.sh --with-dns-plugin=<provider>` (uses `xcaddy`, installs
  to `/usr/local/bin/caddy`, which precedes the apt binary on `PATH`, so the
  gateway picks it up on the next deploy). Castle now owns updates to that binary.
- **`acme` only — a provider API token.** Store it as a secret
  (`~/.castle/secrets/<TOKEN_NAME>`, scope: the DNS provider's "edit DNS records"
  permission for your zone) and map it into the gateway service env in
  `services/castle-gateway.yaml` (`defaults.env`), so Caddy reads it as
  `{env.<TOKEN_NAME>}`. `castle deploy` warns if the domain, env var, or secret is
  missing.
- **`acme` — stage first.** Set `CASTLE_ACME_STAGING=1` at deploy to use Let's
  Encrypt's staging CA (generous rate limits) while verifying issuance, then unset
  it and redeploy for a browser-trusted production cert.

## Choosing a combination

| You have… | Zone (DNS) | Trust (TLS) | Result |
|-----------|-----------|-------------|--------|
| a quick internal tool, HTTP is fine | path prefix or `.lan` host | `off` | `http://node:9000/tool/` |
| a `.lan` LAN, a couple of trusted machines | `*.node.lan` on the router | `internal` | HTTPS, install the CA per device |
| a domain you own + many devices (phones) | `*.sub.domain` on the LAN resolver | `acme` | HTTPS, **no client setup**, internal-only |

The last row is the sweet spot for a multi-device personal LAN, and what this node
runs today: `*.civil.payne.io` (wild-central DNS) + a Let's Encrypt wildcard via
Cloudflare DNS-01, so e.g. `https://openclaw.civil.payne.io/` is trusted on any
device with nothing to install.

## See also

- [registry.md — `proxy`, gateway routes, and the `gateway.tls` modes](registry.md#proxy--how-the-gateway-routes-to-it)
  — the field-level reference (Caddyfile shapes, exact config keys, the CA-download endpoint).
