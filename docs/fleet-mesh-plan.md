# Fleet Mesh Plan — OpenBao + NATS

**Status:** in progress on branch `feat/fleet-mesh-nats-openbao`.
Phases 0–2 + Phase 4 (secret-read backend) complete + single-node verified (live).
Phase 3 (cross-node routing/breaker) and Phase 4 hardening pending the 2nd node.

## Context

Castle's mesh today is a deliberately minimal, read-only gossip: each node
publishes a secret-stripped `NodeRegistry` to Mosquitto MQTT (retained) + an
online/offline LWT, and peers aggregate it into `MeshStateManager`. It is
LAN-only, unauthenticated, carries no secrets, and does nothing with what it
discovers beyond display.

The goal is a **purpose-driven heterogeneous fleet** (media server, security
appliance, TV, comms handler, AI gateway) where nodes come and go as *expected*:
shared LAN-wide config + selected secrets, discoverability + presence, and
binding **by purpose** (a consumer needs `media-index`, not a hostname) with
**circuit-breakers** so churn degrades gracefully instead of hanging.

Two adopted, genuinely-open components (see licensing analysis in chat history):

- **NATS** (CNCF, Apache-2.0) — replaces Mosquitto as the mesh substrate and does
  three jobs in one: pub/sub, **JetStream KV** (shared config + registry), and
  **TTL keys as presence** (a provider's key vanishes on death → the breaker
  trip signal, no separate health plumbing).
- **OpenBao** (Linux Foundation / OpenSSF, MPL-2.0, Vault fork) — the secret
  authority behind castle's existing `${secret:...}` mechanism.

Design stance: **static single-writer `role` authority, no consensus** —
availability comes from followers running cached local state, not failover.
NATS single-node matches that topology. Consensus stays explicitly out of scope.

## Architecture — planes → components → code seams

| Plane | Component | Primary code seam (verified) |
|-------|-----------|------------------------------|
| Transport + KV + presence | NATS (`castle-nats`) | `castle-api/.../mqtt_client.py` (whole file), `main.py` lifespan 62-77, `config.py` Settings |
| Shared config + registry + presence | NATS JetStream KV | `mesh.py` `MeshStateManager`; new KV buckets |
| Secret authority | OpenBao (`castle-openbao`) | `core/.../config.py:307` `_read_secret` (single chokepoint), `castle-api/.../secrets.py` CRUD |
| Binding-by-purpose + breaker | Caddy gateway | `generators/caddyfile.py` `compute_routes` (`remote` kind + ignored `remote_registries` are pre-stubbed), `deploy.py:509-540` `_target_url`/`_requires_env` (local-only today) |
| Authority role | `NodeConfig.role` | `castle_core/registry.py` / `manifest.py` |

## Phased plan

Each phase is independently useful; the risky secret-transport work is last.

### Phase 0 — Stand up the two services (no behavior change)

- **`castle-nats`**: a `SystemdDeployment` + `RunContainer` (`nats:2` with
  JetStream `-js`), data volume `/data/castle/castle-nats`, `reach: internal`
  (`nats.<domain>`). Follow the container YAML shape in `docs/tcp-exposure.md`
  (postgres example). Replace the Mosquitto provisioning in `install.sh`
  (`setup_mqtt`, `seed_mosquitto_config`, image/port consts) with NATS — or
  better, promote it to a bootstrap deployment YAML (today the broker is only a
  shell-provisioned container, not a declared deployment).
- **`castle-openbao`**: `RunContainer` (`openbao/openbao`), data volume, a file
  storage backend, `reach: internal`, **auto-unseal** (local transit/key) so the
  node boots unattended (Decision 2).

### Phase 1 — NATS as the mesh transport (swap Mosquitto, behavior-preserving)

- New `nats_client.py` (async-native `nats-py`) replacing `mqtt_client.py`.
  Registry → a **JetStream KV bucket `castle-registry`** keyed by hostname
  (KV last-value replaces MQTT retained). Presence → a **`castle-presence`**
  bucket with a per-node **TTL key** the node renews (replaces LWT + the 300s
  `STALE_TTL` poll; note `prune_stale` is currently uncalled).
- Wire in `main.py` lifespan; rename `mqtt_*` → `nats_*` in `config.py` (keep
  `CASTLE_API_` prefix). `MeshStateManager` logic is reused; the KV **watch**
  callback drives `update_node`/`set_offline` — and because `nats-py` is
  asyncio-native, the `run_coroutine_threadsafe` cross-thread hop for
  `broadcast("mesh", …)` **goes away**.
- **Preserve the secret-stripping invariant** from `_registry_to_json` (env /
  run_cmd / castle_root never on the wire).
- Rename MQTT-named fields: `models.py` `MeshStatus` (217-226) + frontend
  `types/index.ts` (326-330), `MeshPanel.tsx`. Drop `paho-mqtt`; add `nats-py`.
  Keep zeroconf peer-advert for LAN discovery **and** support explicit NATS seed
  URLs for cross-network (Decision 1); drop the dangling unused `_mqtt._tcp`
  browse. Rewrite `test_mqtt.py` → `test_nats.py`.
- Fixes a latent gap: today the registry is published **on-connect only** (no
  periodic/on-change republish). KV writes on `castle apply` fix this naturally.

### Phase 2 — Shared config + presence via JetStream KV

- Buckets: `castle-config` (shared LAN config, **authority-written only**),
  `castle-registry` (per-node), `castle-presence` (TTL liveness).
- Add static **`role: authority | follower`** to `NodeConfig` (castle.yaml).
  Pin **`civil` = authority** (Decision 3); only the authority may write
  `castle-config`. Authority-down ⇒ shared state read-only, nodes serve cached.
- Followers **watch** `castle-config` and reconcile via `castle apply`. Presence
  key renewal is the churn signal for Phase 3.

### Phase 3 — Cross-node `requires` resolution + gateway binding + breaker (keystone)

- Extend `_target_url`/`_requires_env` (`deploy.py:509-540`) to **fall through to
  the mesh registry** when a `ref` isn't satisfied locally (today it's
  local-only). The ref is already host-independent — this removes the
  "must be local" restriction, not adds a concept.
- Produce the pre-stubbed **`remote` `GatewayRoute`**; thread `remote_registries`
  into `compute_routes` (currently accepted-but-ignored) and into the Caddyfile
  write at `deploy.py:157` (currently passed nothing). Binding = a **stable local
  subdomain route** the gateway re-targets to the remote node's URL — the program
  sees one unchanging URL.
- **Circuit-breaker:** gate the remote route on the `castle-presence` key
  (regenerate + `_reload_gateway` when a provider appears/vanishes), backed by
  Caddy passive health (`fail_duration` / `lb_try_duration`) on the
  `reverse_proxy` line in `_host_matcher_block`. Consumer degraded-mode =
  fallback target or clean 503. (Also carry `health_url` into the registry —
  it's currently dropped on `manager: none` refs.)

### Phase 4 — OpenBao as the secret backend (last; needs the security foundation)

- Introduce a **`SecretBackend` seam** at the single read chokepoint
  `_read_secret` (`config.py:307`) + the `castle-api/.../secrets.py` writer:
  `FileSecretBackend` (default, unchanged) and `OpenBaoBackend`. `${secret:NAME}`
  syntax is untouched; backend selected in castle.yaml or by env.
- Followers auth to OpenBao (token / AppRole); **need-to-know scoping** via
  per-deployment policies. Keep the file backend as fallback; migrate secrets in.

### Cross-cutting prerequisite (gates Phase 4 + any cross-network)

- **Transport hardening**: NATS TLS + nkey/user auth (replace Mosquitto's
  `allow_anonymous`); OpenBao TLS listener. No secret and no cross-network link
  moves until this is in. Cross-network overlay (e.g. Nebula) is orthogonal and
  layers under Caddy later.

## Verification (per phase, end-to-end)

- **P1:** bring up two nodes; confirm registry + presence propagate over NATS and
  the mesh view (`/mesh/status`, System Map) is identical to the MQTT behavior.
- **P2:** write a key to `castle-config` on the authority; observe a follower
  watch fire and `castle apply` reconcile.
- **P3:** define a service on node A that `requires` a ref provided on node B;
  confirm the gateway routes cross-node, then **kill node B** and confirm the
  consumer fails fast (curl returns the degraded 503, not a hang) and **recovers**
  when B returns.
- **P4:** store a secret in OpenBao; confirm a service renders it via
  `EnvironmentFile=` / `--env-file`; then disable the file fallback and confirm
  it still resolves.

## Progress

### Phase 0 — DONE + verified (2026-07-07)

Both services stood up **alongside** the live MQTT mesh (no cutover yet):

- `castle-nats` (`nats:2`, JetStream) — deployment
  `~/.castle/deployments/services/castle-nats.yaml`, config
  `/data/castle/castle-nats/config/nats-server.conf`. Verified: container active,
  `/healthz` ok, JetStream enabled (`/jsz` shows store dir + limits), and a real
  **KV round-trip** — created `castle-registry` (put/get) and a TTL
  `castle-presence` bucket (the presence primitive). Test buckets cleaned up.
- `castle-openbao` (`openbao/openbao:latest`, v2.5.5) — deployment
  `~/.castle/deployments/services/castle-openbao.yaml`, config
  `/data/castle/castle-openbao/config/openbao.hcl`. Verified: initialized (1
  share / threshold 1), unsealed, **KV-v2 secret put/get/delete** round-trip.
  Unseal key + root token stored as castle secrets `OPENBAO_UNSEAL_KEY` /
  `OPENBAO_ROOT_TOKEN`.

**Consciously deferred (tracked):**
1. **Auto-unseal on boot.** OpenBao is unsealed now but a container restart
   re-seals it. The manifest `SystemdSpec` has no `exec_start_post` hook, so
   proper boot-unseal wiring lands with Phase 4 (either a small manifest
   addition or a companion oneshot). Manual recovery: unseal with
   `OPENBAO_UNSEAL_KEY`.
2. **`install.sh` bootstrap parity.** Fresh-install provisioning still seeds
   Mosquitto; adding NATS/OpenBao there (and retiring Mosquitto) is bootstrap-only
   (no runtime impact) and folds in with the Phase 1 cutover.

### Phase 1 — DONE + single-node verified; live cutover done (2026-07-07)

MQTT/Mosquitto transport replaced by NATS JetStream KV.

- New `castle_api/mesh_wire.py` — transport-agnostic registry (de)serialization
  (moved out of `mqtt_client.py`; preserves the secret-stripping invariant).
- New `castle_api/nats_client.py` — `CastleNATSClient`: connects, PUTs its
  registry to the `castle-registry` KV bucket, seeds from existing keys, watches
  for peer PUT/DELETE, heartbeats a re-PUT (crash liveness via the existing
  stale-TTL), and DELETEs its key on graceful stop (immediate peer-offline).
  Async-native → the paho cross-thread `run_coroutine_threadsafe` hop is gone.
- `main.py` lifespan, `config.py` (`nats_enabled`/`nats_url`), `models.py`
  `MeshStatus` (`connected`/`nats_url`), `nodes.py` `/mesh/status` all rewired.
- Frontend: `types/index.ts` `MeshStatus` + `MeshPanel.tsx` updated to the new
  fields. `mqtt_client.py` + `test_mqtt.py` deleted; `test_mesh_wire.py` added.
  `mdns.py` dead `_mqtt._tcp` broker-browse removed. `paho-mqtt` → `nats-py`.
- **Live cutover:** `castle-api.yaml` env → `CASTLE_API_NATS_*`, `requires:
  castle-nats`; applied. castle-api healthy on NATS, `/mesh/status` connected,
  registry (9.7 KiB, 48 deployments) published to KV, **no secrets on the wire**.
- Verification run: ruff clean; 89 api + 196 core tests pass; frontend `tsc`
  clean; runtime KV round-trip confirmed against the live `castle-nats`.

**Pending second node:** two-node mesh-view parity (peer sees peer, offline on
departure) — needs the second LAN node running the NATS-enabled castle-api
pointed at civil's NATS (seed URL) or a clustered `castle-nats`. Revert path if
needed: restore `CASTLE_API_MQTT_*` env — but note `mqtt_client.py` is deleted,
so revert = `git checkout main -- castle-api` then re-apply. The old Mosquitto
`mqtt` service is left running (dormant) as a safety net; retire it once the
second node is proven on NATS.

### Phase 2 — DONE + single-node verified + tested (2026-07-07)

- **`role` field** on `NodeConfig` + `CastleConfig`, wired end-to-end:
  castle.yaml top-level `role:` → config → `_node_config` → registry.yaml →
  mesh wire. **`civil` pinned `role: authority`**; default `follower`.
- **Presence** (`castle-presence`) — a TTL KV bucket each node renews on the
  heartbeat; expiry = the node is gone. Delete-on-stop for immediate departure.
- **Shared config** (`castle-config`) — `get_shared_config` / `put_shared_config`
  (authority-gated: followers raise `PermissionError`), plus a watch loop that
  broadcasts a `config_changed` SSE (the follower `castle apply` reconcile hook
  hangs off this — inert on one node).
- Hardened `stop()` to bound the NATS drain (can't hang systemd shutdown).
- Verified live: all three buckets present, `civil=online` presence,
  `"role": "authority"` on the wire, authority write + follower-deny exercised
  against the running `castle-nats`.
- **Tests added:** `core/tests/test_fleet_role.py` (role config load + registry
  round-trip), `castle-api/tests/test_nats_client.py` (role gating, hermetic),
  role round-trip in `test_mesh_wire.py`. Suites: **200 core + 93 api** pass.

**Pending second node:** the follower-side reconcile (watch `castle-config` →
`castle apply`) is wired as an SSE hook but only meaningful with a peer.

### Phase 4 — secret-read backend DONE + verified + tested (2026-07-07)

- New `core/castle_core/secret_backends.py`: `SecretBackend` protocol,
  `FileSecretBackend` (the historical behavior), `OpenBaoBackend` (KV-v2 read with
  file fallback), and `build_backend()` selecting via `CASTLE_SECRET_BACKEND`
  (default **file** — production is byte-for-byte unchanged until opted in).
- `_read_secret` (the single chokepoint, `config.py`) now delegates to the active
  backend. `${secret:NAME}` syntax untouched.
- OpenBao token bootstraps from the file backend (it can't live in the vault it
  unlocks); a missing key / auth failure / unreachable server all fall through to
  file, so a partly-migrated vault keeps working.
- Verified live against the running `castle-openbao`: a secret stored in the vault
  resolves through `${secret:...}` in openbao mode; file-only secrets resolve via
  fallback; missing → placeholder; **default file mode unchanged**.
- **Tests:** `core/tests/test_secret_backends.py` (file hit/miss, backend
  selection, unreachable-vault + empty-token fallback). Suites: **206 core + 93 api**.

**Remaining for full OpenBao production use (documented, not blocking — nothing
uses the backend until `CASTLE_SECRET_BACKEND=openbao`):**
1. **Write path** — `castle-api/secrets.py` CRUD still writes to files; in openbao
   mode dashboard-set secrets land in file (resolve via fallback) rather than the
   vault. Add `write`/`delete` to the backends + route the API writer through them.
2. **Auto-unseal on boot** (Phase 0 deferral) — OpenBao re-seals on container
   restart. Wire an unseal step (manifest `exec_start_post` or a companion
   oneshot reading `OPENBAO_UNSEAL_KEY`). Not urgent while the backend is unused.
3. **TLS hardening** — NATS + OpenBao are plaintext localhost. Required before
   cross-network or moving real secrets: NATS mTLS + auth, OpenBao TLS listener.

### Phase 3 — cross-node routing + breaker: logic DONE + verified against a real peer (2026-07-07)

**Real second node:** `primer` (192.168.8.129) migrated onto the NATS mesh
(branch checked out, castle-api pointed at `nats://civil:4222` via a systemd
drop-in). civil ↔ primer mesh confirmed over the LAN — **Phase 1 two-node parity
done for real**, not simulated. (This also *restored* the civil↔primer mesh my
Phase 1 cutover had split — primer was still on MQTT→civil.)

- `NodeConfig.address` — routable host peers proxy to (wired through registry +
  wire; falls back to hostname, which civil resolves for primer).
- `compute_routes` now emits **`remote`** routes for services this node
  **consumes** (a local `requires` ref satisfied by an online peer), targeting
  `<peer-address>:<port>`. `_host_remote_block` renders a **fail-fast breaker**
  (2s dial timeout + passive health) for the there-but-wedged case; **presence
  expiry removes the peer from the route set entirely** (gone → no route) — the
  primary breaker.
- `castle_api/mesh_gateway.py` — on peer join/leave/change (+ startup) the API
  re-renders the Caddyfile (same generator `apply` uses + remote routes for
  online peers) and reloads the gateway **iff content changed**.
- **Verified:** 4 hermetic tests (route emitted / address fallback / breaker:
  peer-absent → no route / unconsumed → no route); **resolution against primer's
  real registry** pulled live from the mesh → `castle-api → primer:9020`; and the
  live integration proven a **no-op** on civil (Caddyfile hash unchanged, gateway
  healthy) since civil consumes nothing cross-node yet. Suites: **210 core + 93 api**.

**Remaining:** the full live curl+kill E2E (civil routing to a peer service, then
failing fast on kill) needs a peer-unique service civil consumes — every
underlying piece is verified, but the end-to-end demo needs that provisioning.
primer is now a permanent mesh member on the branch (revert: remove the drop-in +
`git checkout main` on primer).

## Decisions (resolved)

1. **Discovery — both.** Keep mDNS for zero-config LAN peer discovery *and*
   support explicit NATS seed URLs so the mesh can span networks. mDNS is the
   convenience path on-LAN; seed URLs are the cross-network path. Client connects
   via seeds when present, falls back to mDNS-discovered peers on-LAN.
2. **OpenBao unseal — auto for now.** Auto-unseal (local transit/key) so a home
   node boots unattended; designed so we can migrate to manual/stricter unseal
   later (a supported rekey/unseal-migration, not zero-effort but planned for).
   Keep the backend seam clean so the switch is config, not code.
3. **Authority = `civil`.** `civil` (the acme node, `civil.payne.io`) is pinned
   as `role: authority`; all others are followers. **Confirmed:** when `civil` is
   down, shared config/secrets go **read-only** fleet-wide and every node keeps
   serving its own deployments from cached local state.
4. **NATS — single server now, cluster-ready.** Run one `castle-nats` today
   (matches the single-writer authority). Clustering is deferred but must be a
   pure config addition (cluster/routes block + a few more nodes) — no re-architecture.
