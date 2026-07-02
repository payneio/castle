# Supabase Apps in Castle

> **This is a stack — creation-time guidance for writing _new_ database-backed
> web apps.** A stack is a template + conventions, not a runtime requirement.
> `castle program create --stack supabase` scaffolds from it and seeds the
> program's default dev-verb commands. See @docs/registry.md for `commands:`,
> `stack:` (optional), and the deployment `manager` (and derived `kind`).

How to build tiny, database-backed web apps as castle programs that target a
**shared Supabase substrate**. This is Castle's "a stack whose default is a
substrate": the app owns its code (and stays repo-durable), and rents the boring
backend — Postgres + auth + storage + RLS — that an app can't reliably reinvent.

## The model: one shared substrate, many apps

Unlike the other stacks (which scaffold a self-contained process), a supabase app
is **code + migrations that deploy against a shared backend**:

- **The substrate** is one castle service (`supabase`, the `supabase-substrate`
  repo) running self-hosted Supabase via a `manager: systemd` deployment with the
  `compose` launcher. It is shared by
  every supabase app. Stand it up once (see that repo's README).
- **Each app** is a directory of `migrations/` + `functions/` + `public/` that
  deploys onto the substrate. Its rows/blobs live on the substrate; everything
  else rebuilds from git.

Apps are isolated on the shared instance by their **own Postgres schema + RLS**
(and Storage buckets), under **one identity pool** — correct for a single-operator
datalake. Each app owns a schema named after the program (`my-app` → schema
`my_app`); `castle program build` creates and grants it, tracks migrations in a
per-app `<schema>.schema_migrations`, and PostgREST exposes it (castle derives the
substrate's `PGRST_DB_SCHEMAS` from the registered apps). This gives a clean
teardown — `castle delete --purge-data` runs `drop schema <app> cascade` — and
means migration version tokens never collide across apps. Substrate-per-app is
deliberately not supported: ~14 containers per app doesn't scale to "lots of small
ideas," and a DB-backed app is a pet either way.

## Stack

| Layer | Choice |
|-------|--------|
| **Backend** | Self-hosted Supabase (Postgres + PostgREST + GoTrue + Storage + Realtime + Edge Functions) |
| **Client** | `@supabase/supabase-js` (from a CDN; no build step required) |
| **Migrations** | Ordered SQL files, applied by a versioned idempotent runner |
| **Functions** | Deno edge functions |
| **UI** | Static HTML/JS in `public/`, served in place by the gateway |
| **Auth** | GoTrue + Postgres Row-Level Security |

## Project layout

```
my-app/
├── supabase.app.yaml       # substrate wiring + auth policy (public/private/shared)
├── migrations/
│   └── 0001_init.sql       # versioned, idempotent, forward-only
├── functions/
│   └── hello/index.ts      # deno edge function
├── public/
│   ├── index.html          # static UI — talks to the substrate via supabase-js
│   └── config.js           # SUPABASE_URL + anon key (public-safe)
└── CLAUDE.md
```

Registered as a program with `build.outputs: [public]` plus a `manager: caddy`
deployment (`root: public`, derived **kind: static**), so the
gateway serves `public/` in place at `/my-app/` — no service, no process.

## supabase.app.yaml

```yaml
name: my-app
substrate: supabase        # the shared castle service this app deploys against
auth: public               # public | private | shared: [handles]
schema: my_app             # this app's isolated Postgres schema (frontend: db.schema)
```

## Migrations

`migrations/*.sql` are **numbered, forward-only, and idempotent**. `castle program
build my-app` runs the versioned migration runner: it creates + grants the app's
schema, ensures a per-app `<schema>.schema_migrations` table, reads applied
versions, and applies only the **unapplied** files (in filename order) with
`search_path` set to the app schema — each in a single transaction with its
version-insert, so a failed migration records nothing and the next build retries
it. Never edit an applied migration; add a new numbered file.

Because the runner sets `search_path` to the app's own schema, write **unqualified**
names — they land in `<schema>`, not `public`:

```sql
-- migrations/0001_init.sql
create table if not exists entries (
    id bigint generated always as identity primary key,
    message text not null,
    created_at timestamptz not null default now()
);
alter table entries enable row level security;
create policy "my_app_read"  on entries for select using (true);
create policy "my_app_write" on entries for insert with check (true);
```

The runner connects via `SUPABASE_DB_URL`, or builds one from the generated
`SUPABASE_POSTGRES_PASSWORD` secret against the substrate's direct Postgres port
(host **5433**, `SUPABASE_DB_HOST_PORT` to override). `psql` must be on PATH; a
missing URL or client fails loud with guidance.

The frontend selects the app schema through supabase-js:

```js
const db = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, { db: { schema: SCHEMA } });
```

### Teardown

An app's rows live only on the substrate, so an ordinary `castle delete my-app`
leaves the schema intact (and says so). To destroy the data too:

```bash
castle delete my-app --purge-data      # drop schema my_app cascade
```

`castle deploy` then prunes the schema from `PGRST_DB_SCHEMAS`; **restart the
`supabase` service** for PostgREST to pick up the added/removed schema list.

## Auth, RLS & the three privacy layers

`auth:` in `supabase.app.yaml` declares the policy. **RLS protects rows, but it is
not sufficient on its own** — a leaked URL to a `private` app would still serve the
static shell and any known Storage URL. So a non-public app must enforce privacy at
**three** layers:

1. **Rows** — RLS locks rows to `auth.uid()` (owner) or a shared allowlist.
2. **Static shell** — an auth check gates serving `public/` (unauthenticated
   requests get login/denied, never the app).
3. **Storage** — served via short-lived **signed URLs**, never long-lived public
   object URLs.

A `public` app intentionally skips shell/Storage gating (anon read/write, still
row-gated).

## Edge functions

`functions/<name>/index.ts` are deno functions deployed to the substrate's
edge-runtime. Privileged work (anything needing the `service_role` key) happens
here, server-side — **never** browser-direct. The app frontend calls the function;
the function holds credentials and can meter usage.

## Gateway & secure context

A supabase app is a static deployment (`manager: caddy`; its `public/` is served
in place), so the gateway serves it at its own subdomain
`<name>.<gateway.domain>`. With
`gateway.tls: acme` that subdomain is HTTPS — a **secure context**, which apps
using **auth or WebCrypto** require — with no private CA to install. (The substrate
service itself is likewise at `supabase.<gateway.domain>`.) See
@docs/dns-and-tls.md.

## Commands

```bash
castle program create my-app --stack supabase --description "..."   # scaffold + register
castle program build my-app        # apply unapplied migrations to the substrate
castle program test  my-app        # deno test over functions/ (if deno present)
castle deploy && castle gateway reload    # serve the static UI at /my-app/
```

## Scaffolding

`castle program create --stack supabase` generates the full layout above and
registers the program as a static frontend. Set the anon key in `public/config.js`
(`cat ~/.castle/secrets/SUPABASE_ANON_KEY`), edit your migrations, and build.

See @docs/registry.md for the `compose` launcher, the substrate deployment definition,
and the full registry reference. The substrate itself lives in the
`supabase-substrate` repo (vendored, pinned self-hosted Supabase).
