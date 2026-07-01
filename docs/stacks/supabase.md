# Supabase Apps in Castle

> **This is a stack — creation-time guidance for writing _new_ database-backed
> web apps.** A stack is a template + conventions, not a runtime requirement.
> `castle program create --stack supabase` scaffolds from it and seeds the
> program's default dev-verb commands. See @docs/registry.md for `commands:`,
> `stack:` (optional), and `behavior:`.

How to build tiny, database-backed web apps as castle programs that target a
**shared Supabase substrate**. This is Castle's "a stack whose default is a
substrate": the app owns its code (and stays repo-durable), and rents the boring
backend — Postgres + auth + storage + RLS — that an app can't reliably reinvent.

## The model: one shared substrate, many apps

Unlike the other stacks (which scaffold a self-contained process), a supabase app
is **code + migrations that deploy against a shared backend**:

- **The substrate** is one castle service (`supabase`, the `supabase-substrate`
  repo) running self-hosted Supabase via the `compose` runner. It is shared by
  every supabase app. Stand it up once (see that repo's README).
- **Each app** is a directory of `migrations/` + `functions/` + `public/` that
  deploys onto the substrate. Its rows/blobs live on the substrate; everything
  else rebuilds from git.

Apps are isolated on the shared instance by **table prefix + RLS** in the shared
`public` schema (and Storage buckets), under **one identity pool** — correct for a
single-operator datalake. Substrate-per-app is deliberately not supported: ~14
containers per app doesn't scale to "lots of small ideas," and a DB-backed app is
a pet either way.

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

Registered as a `behavior: frontend` program with `build.outputs: [public]`, so the
gateway serves `public/` in place at `/my-app/` — no service, no process.

## supabase.app.yaml

```yaml
name: my-app
substrate: supabase        # the shared castle service this app deploys against
auth: public               # public | private | shared: [handles]
table_prefix: my_app_
```

## Migrations

`migrations/*.sql` are **numbered, forward-only, and idempotent**. `castle program
build my-app` runs the versioned migration runner: it ensures a
`public.schema_migrations` table, reads applied versions, and applies only the
**unapplied** files (in filename order), each in a single transaction with its
version-insert — so a failed migration records nothing and the next build retries
it. Never edit an applied migration; add a new numbered file.

```sql
-- migrations/0001_init.sql
create table if not exists public.my_app_entries (
    id bigint generated always as identity primary key,
    message text not null,
    created_at timestamptz not null default now()
);
alter table public.my_app_entries enable row level security;
create policy "my_app_read"  on public.my_app_entries for select using (true);
create policy "my_app_write" on public.my_app_entries for insert with check (true);
```

The runner connects via `SUPABASE_DB_URL`, or builds one from the generated
`SUPABASE_POSTGRES_PASSWORD` secret against `localhost:5432`. `psql` must be on
PATH; a missing URL or client fails loud with guidance.

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

A `public` app is fine on the gateway's HTTP static route at `/my-app/`. An app
that uses **auth or WebCrypto** needs a **secure context**, so give it its own
HTTPS host route instead — `proxy.caddy.host: my-app.lan` with `gateway.tls:
internal` — exactly like the substrate itself (`supabase.lan`). See the "HTTPS for
host routes" section of @docs/registry.md.

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

See @docs/registry.md for the `compose` runner, the substrate service definition,
and the full registry reference. The substrate itself lives in the
`supabase-substrate` repo (vendored, pinned self-hosted Supabase).
