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
of two TLS modes. They're orthogonal: you pick a resolution strategy and a trust
strategy, and any working combination is fine.

## The gateway is the single ingress

Every gateway-reachable service goes through the Caddy **gateway**. Exposure is a
single **checkbox** (`proxy: true` on a service):

- **unchecked** — the service is reachable only at its own `host:port` (no gateway
  route, no DNS name).
- **checked** — the gateway routes the whole subdomain **`<service-name>.<domain>`**
  to the backend root. The subdomain is always the service name.

There are **no path-prefix routes**: a whole subdomain maps to the backend root, so
root-relative asset URLs and `window.location`-derived WebSocket URLs just work
(Caddy proxies WebSocket upgrades transparently). Each checked service gets its own
DNS name and shares the gateway's TLS cert. The rest of this document is about
making those subdomains **resolve** (DNS) and be **trusted** (TLS).

## DNS: making a name resolve to the node

A subdomain does nothing until it resolves **to this node** on the clients that
browse it. Castle does **not** run DNS; you add one record to your **LAN's DNS
server** — usually the router. A single **wildcard** covers every subdomain, so new
services need no further DNS edits:

```
address=/<sub>.<domain>/<node-ip>     # dnsmasq (e.g. on the router)
```

(or the equivalent wildcard `A` record in whatever your router's DNS uses). Pin
`<node-ip>` with a **DHCP reservation** — the wildcard hardcodes it.

### Split-horizon: internal names, no public exposure

The names resolve **only inside the LAN**. You own the domain publicly (needed so
DNS-01 can issue a real cert — below), but the **public** zone has no `A` records
for the services — only your LAN's wildcard points at the node. So the services are
trusted (real cert) yet reachable only from the LAN, never the internet.

## TLS: two trust modes

`gateway.tls` (in `castle.yaml`) picks how host routes are served. It's a per-node
choice.

| `gateway.tls` | What the browser gets | Client setup | Use when |
|---------------|-----------------------|--------------|----------|
| `off` *(default)* | plain HTTP on `:9000` | none | you don't need HTTPS; a node with no public domain |
| `acme` | HTTPS from a **real Let's Encrypt wildcard** | **nothing** | you own a domain; any/multiple devices (phones, etc.) |

### `off` — plain HTTP

The gateway generates `auto_https off` and listens on a bare `:9000`. Reach it at
`http://<node>:9000/`. Simple, but a non-`localhost` HTTP page is **not** a browser
"secure context" (see below), and there's no encryption. For a node with no public
domain, this is the mode — reach secure-context apps via `http://localhost` /
direct ports on the node itself.

> A private-CA option (Caddy's `tls internal`) existed but was removed: it required
> installing a custom root CA on every device, which some platforms (Android
> browsers; Firefox, which uses its own store) make painful — the exact problem
> `acme` solves without any client setup.

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

One `*.<domain>` site means a **single cert** covers every subdomain, and Caddy
**auto-renews** it — adding a service needs no new cert and no DNS-01 round trip.
Every subdomain is the **service name** (`<name>.<domain>`), so services stay
domain-agnostic — switching `gateway.domain` needs no service edits.

This is the recommended mode when you own a domain and want to reach services from
arbitrary devices.

## Why HTTPS at all — the secure-context requirement

Beyond eavesdropping protection, HTTPS unlocks browser capabilities gated to a
**secure context**: `crypto.subtle` (WebCrypto), service workers, and anything
built on them (device identity, end-to-end crypto). Browsers treat only `https://`
and `http://localhost` as secure — a plain-HTTP page on a LAN hostname is **not**,
so such apps break there. That's the concrete reason to move a host route to
`acme` rather than leaving it on `off`.

Note: a host served over HTTPS has its own **origin** (`https://foo.example`, no
port). An app that allowlists origins, or an OAuth/token flow, must include the new
origin — moving a service onto HTTPS changes its origin.

## Putting a service on trusted HTTPS — the recipe

1. **Check the box.** Add `proxy: true` to the service — it's now exposed
   at `<service-name>.<gateway.domain>` (rename the service to change the name).
2. **Make the name resolve.** Add (or rely on) the LAN wildcard for the zone
   (§DNS). Verify: `dig +short <name>.<domain>` → the node's IP.
3. **Set `gateway.tls: acme`** (with `domain`/`acme_email`), plus the operational
   prerequisites (below).
4. **Deploy & reload:** `castle apply` regenerates the Caddyfile and reloads Caddy.
5. **Update the app's origin allowlist** if it has one (§secure context).

## Operational prerequisites

`acme` needs the gateway to bind privileged ports, plus a plugin-enabled Caddy and
a DNS token.

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
  `deployments/castle-gateway.yaml` (`defaults.env`), so Caddy reads it as
  `{env.<TOKEN_NAME>}`. `castle apply` warns if the domain, env var, or secret is
  missing.
- **`acme` — stage first.** Set `CASTLE_ACME_STAGING=1` at deploy to use Let's
  Encrypt's staging CA (generous rate limits) while verifying issuance, then unset
  it and redeploy for a browser-trusted production cert.

## Choosing a combination

| You have… | Zone (DNS) | Trust (TLS) | Result |
|-----------|-----------|-------------|--------|
| a quick internal tool, HTTP is fine | a `.lan` host, or none | `off` | `http://<node>:9000/` (dashboard) + services by port |
| a node with no public domain, needs a secure context | — | `off` | reach it via `http://localhost` / direct port on the node |
| a domain you own + any devices (phones) | `*.<sub>.<domain>` on the LAN resolver | `acme` | HTTPS, **no client setup**, internal-only |

The last row is the sweet spot for a personal LAN: a `*.<sub>.<domain>` wildcard on
the LAN resolver + a Let's Encrypt wildcard via DNS-01, so e.g.
`https://<service>.<sub>.<domain>/` is trusted on any device with nothing to
install.

## See also

- [registry.md — `proxy`, gateway routes, and the `gateway.tls` modes](registry.md#proxy--how-the-gateway-routes-to-it)
  — the field-level reference (Caddyfile shapes, exact config keys, DNS-01 setup).
