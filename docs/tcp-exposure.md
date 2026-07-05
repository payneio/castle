# TCP exposure & castle-managed TLS material

> Status: **design / not yet implemented.** This specs the `reach` exposure
> ladder, raw-TCP service exposure (postgres, redis, …), and how castle
> materializes its ACME wildcard cert onto a service so a raw port presents a
> *trusted* cert — generically, with **no protocol knowledge in castle's code**.

Read `docs/dns-and-tls.md` first — this builds on the acme wildcard model.

---

## 1. Why

The gateway (Caddy) is HTTP-only: it multiplexes subdomains onto `:443` by TLS
SNI. Raw-TCP services (postgres/5432, redis/6379, …) can't ride that — the
protocols either send a cleartext preamble before any ClientHello (postgres,
mysql) so there's no SNI to route on, or they simply aren't HTTP. But they don't
*need* the gateway: the wildcard DNS record already points **every** subdomain at
the node, and each service already has its own port. So "expose a TCP service
internally" reduces to two things castle can do without a proxy:

1. **bind the port** on the LAN, and
2. **put a trusted cert on the service** — the one wildcard cert we already own,
   which is valid for `<name>.<domain>` (wildcards match).

The only per-service variation is *what file format the cert takes* and *how the
service is told to re-read it*. Both are pushed into the deployment yaml. Castle
stays a cert-mover and a signal-sender.

Public raw-TCP is a separate, Cloudflare-edge concern — see §6.

---

## 2. The `reach` ladder (replaces `proxy` / `public`)

Exposure becomes one protocol-agnostic enum on the deployment:

| `reach` | meaning |
|---------|---------|
| `off` *(default)* | reachable only at its own `host:port` (no gateway route, no DNS intent) |
| `internal` | reachable at `<name>.<domain>` — HTTP via the gateway, or TCP via bind + wildcard DNS |
| `public` | *also* projected to the internet (HTTP via tunnel origin; TCP via `cloudflared access tcp`) |

`reach` is orthogonal to **protocol**, which is described by `expose.http` /
`expose.tcp` (ports live there). One field says *how far it reaches*; the other
says *what it speaks*.

### Legacy mapping (back-compat normalizer)

`castle` accepts the old fields and normalizes them so existing yamls keep
working; `castle apply` can rewrite them on next write:

| old | new |
|-----|-----|
| *(neither)* | `reach: off` |
| `proxy: true` | `reach: internal` |
| `proxy: true` + `public: true` | `reach: public` |
| `public: true` without `proxy` | *(already invalid — unchanged)* |

---

## 3. Manifest models (`core/src/castle_core/manifest.py`)

```python
class Reach(str, Enum):
    OFF = "off"
    INTERNAL = "internal"
    PUBLIC = "public"


class TlsMaterial(str, Enum):
    OFF = "off"           # service does its own TLS (or none)
    PAIR = "pair"         # cert.pem + key.pem (postgres, redis, most daemons)
    COMBINED = "combined" # one file: key+cert concatenated (mongodb, haproxy)


class TlsSpec(BaseModel):
    material: TlsMaterial = TlsMaterial.OFF
    # Optional zero-downtime reload argv run after re-materialize on renewal.
    # Default: castle restarts the deployment (fine for a ~60-day cadence).
    reload: list[str] | None = None


class TcpExposeSpec(BaseModel):
    port: int = Field(ge=1, le=65535)
    tls: TlsSpec | None = None      # step 3; absent = service does its own TLS
    # No bind-host field: publishing the port on the LAN is the deployment's own
    # job (a container's run.ports, or a native service binding 0.0.0.0). castle
    # doesn't rebind it, so a `host:` here would be an ignored (misleading) field.


class ExposeSpec(BaseModel):
    http: HttpExposeSpec | None = None
    tcp: TcpExposeSpec | None = None

    @model_validator(mode="after")
    def _one_protocol(self) -> "ExposeSpec":
        if self.http and self.tcp:
            raise ValueError("a deployment exposes http OR tcp, not both")
        return self
```

On `SystemdDeployment`, **replace** `proxy: bool` / `public: bool` with:

```python
    reach: Reach = Reach.OFF

    @model_validator(mode="after")
    def _validate(self) -> "SystemdDeployment":
        if self.reach == Reach.PUBLIC and not (self.expose and (self.expose.http or self.expose.tcp)):
            raise ValueError("reach: public requires an exposed http or tcp port")
        tls = self.expose and self.expose.tcp and self.expose.tcp.tls
        if tls and tls.material != TlsMaterial.OFF and self.reach == Reach.OFF:
            raise ValueError("tls.material needs reach: internal|public")
        return self
```

`CaddyDeployment` (static) also gains `reach: Reach = Reach.INTERNAL`
(constrained to `internal|public` — a static site is inherently served), and its
old `public: bool` normalizes to `reach`.

> **acme prerequisite:** `tls.material != off` only makes sense when
> `gateway.tls == acme` with a domain — otherwise there's no wildcard cert to
> copy. `castle apply` / `castle doctor` warn if `material` is set without acme.

---

## 4. Placeholders (`deploy.py` `_env_context`)

When a deployment declares `expose.tcp.tls.material != off`, castle adds these to
the placeholder context (alongside the existing `${port}`/`${data_dir}`/… set),
pointing at the materialized copies under `‹data_dir›/tls/`:

| placeholder | expands to (host path) |
|-------------|------------------------|
| `${tls_dir}` | `‹DATA_DIR›/‹config_key›/tls` — mount this into a container |
| `${tls_cert}` | `${tls_dir}/cert.pem` (leaf + chain) |
| `${tls_key}` | `${tls_dir}/key.pem` |
| `${tls_pem}` | `${tls_dir}/combined.pem` (`material: combined`) |
| `${tls_ca}` | `${tls_dir}/chain.pem` (issuer chain) |

They resolve through the one shared `${...}` resolver (`resolve_placeholders`,
which `resolve_env_split` also uses) — for a container these `${key}` refs are
expanded in `run.env`, `run.volumes`, `run.args`, `run.command`, `run.workdir`,
`run.user`, and `run.tmpfs` alike. To pass a **literal** `${key}` through to the
container's own shell/env (rather than have castle expand it), write `$${key}`
(docker-compose-style `$$` escape).

**Native service** (python/command launcher) references the host paths directly:

```yaml
reach: internal
expose:
  tcp: { port: 6379, tls: { material: pair } }
defaults:
  env:
    REDIS_TLS_CERT: ${tls_cert}
    REDIS_TLS_KEY: ${tls_key}
```

**Container** mounts `${tls_dir}` and uses in-container paths (the host→container
path differs, so the author maps it — consistent with our "image specifics live
in the deployment" rule):

```yaml
reach: internal
expose:
  tcp: { port: 5432, tls: { material: pair } }
run:
  launcher: container
  user: ${uid}:${gid}          # default for castle containers — see below
  image: postgres:17
  ports: { '5432': 5432 }
  tmpfs: [/var/run/postgresql]  # image runtime dir, needs to be writable by our uid
  volumes:
    - /data/castle/postgres/data:/var/lib/postgresql/data
    - ${tls_dir}:/tls:ro
  args: ['-c','ssl=on','-c','ssl_cert_file=/tls/cert.pem','-c','ssl_key_file=/tls/key.pem']
```

### Container key ownership — dissolved by uid uniformity (verified)

The naive problem: postgres refuses a key that isn't `0600` **and owned by the
process uid** (999 in the stock image), while castle writes files as the host
user (1000), and bind mounts preserve host uid — so 999 can't read them, and
chowning across uids needs privilege. Rather than patch that with a privileged
chown, castle **runs containers as the invoking user** (`--user ${uid}:${gid}`,
the default on `RunContainer`, overridable per deployment). Then the process, its
data dir, its secrets *and* its certs are all one uid — nothing to chown, for any
service. Verified end-to-end against `postgres:17`:

```
docker run --user 1000:1000 --tmpfs /var/run/postgresql \
  -v …/key.pem:/tls/key.pem:ro (0600, owned 1000) … postgres:17 -c ssl=on …
→ pg_stat_ssl: t | TLSv1.3     # SSL on, real TLS 1.3, key read fine, zero privilege
```

The only image-specific detail is a writable runtime dir (`--tmpfs
/var/run/postgresql`) — declared in the deployment yaml, not castle. `RunContainer`
gains a `user: str = "${uid}:${gid}"` field and a `tmpfs: list[str]`; castle stays
privilege-free. (One-time migration cost: an existing data dir owned by 999 gets
chowned to the runtime uid once when a service adopts this — not per-renewal.)

---

## 5. Cert materialization + the `cert_obtained` hook

### The materializer (`castle_core`, protocol-agnostic)

`materialize_tls(config, name, dep) -> bool` — for one deployment with
`tls.material != off`:

1. Locate the source wildcard in Caddy's store by glob (prefer prod over staging):
   `~/.local/share/caddy/certificates/acme-v02*-directory/wildcard_.‹domain›/wildcard_.‹domain›.{crt,key}`
   (falls back to `acme-staging-v02*` when `CASTLE_ACME_STAGING=1`).
2. Compare a hash of the source to the materialized copy; **return False if
   unchanged** (idempotent — safe to call every apply and every renewal).
3. Write `‹data_dir›/tls/` in the requested format:
   - `pair` → `cert.pem` (the `.crt`, already leaf+chain), `key.pem`
   - `combined` → `combined.pem` = `key.pem` + `cert.pem` concatenated
   - `chain.pem` (for `${tls_ca}`) is written for either format — the **issuer
     chain** (intermediates only, leaf stripped), a real CA bundle distinct from
     the leaf-bearing `cert.pem`/`combined.pem`.
   - files `0600` (key) / `0644` (cert); dir `0700`.
4. Apply `tls.owner` (via the privileged chown step, §4) when set.
5. Return True (changed).

`reconcile_tls(config)` — walk all deployments; `materialize_tls` each; for those
that changed, run `tls.reload` argv **or** `castle restart ‹name›`. Idempotent;
prints a summary.

### Wiring

- **`castle apply`** calls `materialize_tls` for each affected deployment before
  (re)starting it — so first deploy has certs in place.
- **Event-driven (the hook you wanted) — VERIFIED.** Build Caddy with
  `github.com/mholt/caddy-events-exec` (add the `--with` to `install.sh`'s xcaddy
  build, alongside `caddy-dns/cloudflare`) and add to the Caddyfile global options:
  ```
  {
      email …
      acme_dns cloudflare {env.CLOUDFLARE_API_TOKEN}
      events {
          on cert_obtained exec castle tls reconcile
      }
  }
  ```
  Caddy fires `cert_obtained` on every issuance **and renewal** (renewal reuses
  the same event with `renewal: true`); the handler runs `castle tls reconcile`,
  which re-copies the rotated wildcard and reloads consumers. Immediate, no polling.
  > **Proven end-to-end** (2026-07-03): built into our Caddy 2.11.4, an
  > `on cert_obtained exec` handler fired on internal-CA issuance with event data
  > (`issuer=local`, `identifier`, `certificate_path`) correctly passed. Since the
  > emit is issuer-agnostic (CertMagic `config.go`), acme renewal fires it identically.
  > Two caveats from the test: (a) the module is **experimental** — pin the xcaddy
  > build and re-verify on Caddy upgrades; (b) `exec` runs the command in the
  > **background and swallows its exit code** — so `castle tls reconcile` must be
  > idempotent and log its *own* outcome (don't rely on Caddy surfacing failures).
- **Safety net:** a nightly `castle-tls-reconcile` job (`manager: systemd` +
  `schedule`) also runs `castle tls reconcile` — catches a missed event, a Caddy
  restart, or a manual cert swap. Same idempotent call, so belt-and-suspenders is
  free.

New CLI: `castle tls reconcile [--plan]` (thin wrapper over `reconcile_tls`), and
`castle tls status` to show, per deployment, source vs materialized cert fingerprint
+ expiry.

---

## 6. `reach: public` for TCP (later, separable)

Public raw-TCP can't reach an unmodified client below Cloudflare Enterprise
(Spectrum arbitrary-TCP is Enterprise-gated). The free, minimal path rides the
**existing** tunnel:

- `tunnel.py` emits an extra ingress entry per public TCP deployment:
  `{ hostname: ‹name›.‹public_domain›, service: tcp://localhost:‹port› }`.
- castle ensures a self-hosted **Access** app + policy over that hostname.
- `castle` prints the client connect line:
  `cloudflared access tcp --hostname ‹name›.‹public_domain› --url localhost:‹local›`.

The client runs `cloudflared access tcp` (or WARP private-network) and points its
tool (`psql`/`redis-cli`) at `localhost`. This is the correct posture for a DB —
authenticated tunnel, never an open port. Build this only when wanted.

---

## 7. Generality check

Same castle code, different yaml — the postgres-ness is two env/arg mappings + a
format choice, nothing more:

| service | `material` | consumes | reload |
|---------|-----------|----------|--------|
| postgres | `pair` | `ssl_cert_file` / `ssl_key_file` args | SIGHUP / restart |
| redis | `pair` | `--tls-cert-file/--tls-key-file/--tls-ca-cert-file` | restart |
| mongodb | `combined` | `net.tls.certificateKeyFile: /tls/combined.pem` | restart |
| arbitrary | `pair` | its own `TLS_CERT`/`TLS_KEY` env | restart |

`pair` vs `combined` is the entire protocol-variation surface.

---

## 8. Build order

1. ~~**`reach` enum + normalizer** for HTTP (replace `proxy`/`public`); migrate
   existing yamls.~~ **DONE (2026-07-03).** Canonical `reach` on
   Systemd/CaddyDeployment; `_reach_from_legacy` before-validator accepts legacy
   input; `proxy`/`public` are derived read-only accessors. 13 yamls migrated
   (`apply --plan` = already converged); app toggles + `deploy_create` write
   `reach`; all suites green.
2. ~~**`expose.tcp` + bind** (internal TCP, `material: off`): `postgres.civil…:5432`
   works, service does its own TLS.~~ **DONE (2026-07-03).** `TcpExposeSpec` +
   `ExposeSpec` one-protocol validator; `http_exposed`/`tcp_port` predicates so a
   TCP `reach: internal` yields **no** Caddy route (correctness); registry carries
   `tcp_port`; `castle service info` shows the `<name>.<domain>:<port>` endpoint;
   public-TCP guarded (step 5). Applied to `postgres` — verified: `psql -h
   postgres.civil.payne.io` connects by name, postgres absent from HTTP routes,
   `apply --plan` still converged.
3. **TLS material + placeholders + `materialize_tls`** — **CODE DONE (2026-07-03).**
   `TlsSpec`/`TlsMaterial`; `${tls_dir|cert|key|pem|ca}` + `${uid}/${gid}`
   placeholders; `RunContainer.user`/`tmpfs` (uid-uniformity, no chown);
   `core/tls.py` (`wildcard_cert`/`materialize_tls`/`materialize_all`); wired into
   `castle apply`; unit-tested in isolation (pair/combined/idempotency/stale-clean).
4. **`cert_obtained` hook + `castle tls`** — **CODE DONE (2026-07-03).** Generator
   emits the `events { on cert_obtained exec castle tls reconcile }` block, **gated
   on `CASTLE_CADDY_CERT_HOOK=1`** so the current (no-plugin) gateway is unaffected;
   `castle tls reconcile|status` CLI; `reconcile_tls` idempotent + self-logging.
   *(Nightly safety-net job: TODO.)*
   → **LIVE ROLLOUT DONE (2026-07-03).** (a) `/usr/local/bin/caddy` rebuilt with
   cloudflare-dns + `caddy-events-exec` (old binary → `caddy.bak-pre-events`;
   `install.sh` bakes both plugins). (b) Gate is a durable **`gateway.cert_hook`**
   config flag (not an env var) → NodeConfig → generator; set true, `apply`'d; the
   running gateway's admin API confirms the `cert_obtained → castle tls reconcile`
   subscription is live. (c) postgres enabled: `user: ${uid}:${gid}` + `tmpfs` +
   `tls.material: pair`; data dir chowned 999→1000 once (cold backup at
   `/data/castle/postgres-data-backup-pre-tls.tar.gz`); WAL-recovered clean.
   **Verified:** `psql -h postgres.civil.payne.io sslmode=verify-full sslrootcert=system`
   → "verify-full OK" against the trusted LE wildcard; `castle` + `litellm` DBs intact.
   Also landed: `${uid}/${gid}` in the placeholder context + placeholder expansion
   in container run fields (`volumes`/`args`/`user`/`tmpfs`) so `${tls_dir}` mounts work.
5. **`reach: public` for TCP** (tunnel `tcp://` + Access + connect line) — when
   wanted.
